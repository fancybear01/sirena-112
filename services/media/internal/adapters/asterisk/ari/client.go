package ari

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
	"github.com/gorilla/websocket"
)

// Client talks to Asterisk ARI over HTTP and WebSocket.
type Client struct {
	baseURL       string
	username      string
	password      string
	app           string
	http          *http.Client
	log           *slog.Logger
	rtpPublicHost string
	rtpListenHost string
	rtpPort       int
	echoFactory   ports.EchoFactory

	mu       sync.Mutex
	handler  ports.EventHandler
	runtimes map[string]*callRuntime // key: callID
	byChan   map[string]string       // channelID -> callID
}

type callRuntime struct {
	callID          string
	sessionID       string
	aiSessionID     string
	echo            ports.EchoSession
	bridgeID        string
	externalMediaID string
	channelID       string
	bridged         bool
}

// Config wires ARI client dependencies.
type Config struct {
	BaseURL       string
	Username      string
	Password      string
	App           string
	RTPPublicHost string
	RTPListenHost string
	RTPPort       int
	EchoFactory   ports.EchoFactory
	Log           *slog.Logger
}

func NewClient(cfg Config) *Client {
	return &Client{
		baseURL:       strings.TrimRight(cfg.BaseURL, "/"),
		username:      cfg.Username,
		password:      cfg.Password,
		app:           cfg.App,
		http:          &http.Client{Timeout: 10 * time.Second},
		log:           cfg.Log,
		rtpPublicHost: cfg.RTPPublicHost,
		rtpListenHost: cfg.RTPListenHost,
		rtpPort:       cfg.RTPPort,
		echoFactory:   cfg.EchoFactory,
		runtimes:      map[string]*callRuntime{},
		byChan:        map[string]string{},
	}
}

func (c *Client) Ready(ctx context.Context) error {
	resp, err := c.do(ctx, http.MethodGet, "/asterisk/info", nil, nil)
	if err != nil {
		return fmt.Errorf("%w: %v", domain.ErrARIUnavailable, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		return fmt.Errorf("%w: status %d", domain.ErrARIUnavailable, resp.StatusCode)
	}
	return nil
}

func (c *Client) StartCall(ctx context.Context, req ports.StartCallRequest) (ports.CallResources, error) {
	endpoint := req.SIPAddress
	if !strings.Contains(endpoint, "/") {
		endpoint = "PJSIP/" + endpoint
	}

	echo, boundPort, err := c.echoFactory.Create(c.rtpListenHost, c.rtpPort)
	if err != nil {
		return ports.CallResources{}, fmt.Errorf("rtp listen: %w", err)
	}
	// Own lifetime via DestroyCall; do not bind to the HTTP request context.
	if err := echo.Start(context.Background()); err != nil {
		_ = echo.Stop(context.Background())
		return ports.CallResources{}, err
	}

	bridgeID, err := c.createBridge(ctx, req.CallID)
	if err != nil {
		_ = echo.Stop(context.Background())
		return ports.CallResources{}, err
	}

	extHost := fmt.Sprintf("%s:%d", c.rtpPublicHost, boundPort)
	extID, err := c.createExternalMedia(ctx, extHost)
	if err != nil {
		_ = c.destroyBridge(ctx, bridgeID)
		_ = echo.Stop(context.Background())
		return ports.CallResources{}, err
	}
	if err := c.addToBridge(ctx, bridgeID, extID); err != nil {
		_ = c.hangupChannel(ctx, extID)
		_ = c.destroyBridge(ctx, bridgeID)
		_ = echo.Stop(context.Background())
		return ports.CallResources{}, err
	}

	channelID, err := c.originate(ctx, endpoint, req)
	if err != nil {
		_ = c.hangupChannel(ctx, extID)
		_ = c.destroyBridge(ctx, bridgeID)
		_ = echo.Stop(context.Background())
		return ports.CallResources{}, err
	}

	rt := &callRuntime{
		callID:          req.CallID,
		sessionID:       req.SessionID,
		aiSessionID:     req.AISessionID,
		echo:            echo,
		bridgeID:        bridgeID,
		externalMediaID: extID,
		channelID:       channelID,
	}
	c.mu.Lock()
	c.runtimes[req.CallID] = rt
	c.byChan[channelID] = req.CallID
	c.byChan[extID] = req.CallID
	c.mu.Unlock()

	c.log.Info("ari call started",
		"callId", req.CallID,
		"sessionId", req.SessionID,
		"channelId", channelID,
		"bridgeId", bridgeID,
		"externalMediaId", extID,
		"rtpHost", extHost,
	)

	return ports.CallResources{
		ChannelID:       channelID,
		BridgeID:        bridgeID,
		ExternalMediaID: extID,
	}, nil
}

func (c *Client) Hangup(ctx context.Context, channelID string) error {
	return c.hangupChannel(ctx, channelID)
}

func (c *Client) DestroyCall(ctx context.Context, res ports.CallResources) error {
	var first error
	capture := func(err error) {
		if err != nil && first == nil {
			first = err
		}
	}
	if res.ChannelID != "" {
		capture(c.hangupChannel(ctx, res.ChannelID))
	}
	if res.ExternalMediaID != "" {
		capture(c.hangupChannel(ctx, res.ExternalMediaID))
	}
	if res.BridgeID != "" {
		capture(c.destroyBridge(ctx, res.BridgeID))
	}

	c.mu.Lock()
	defer c.mu.Unlock()
	for callID, rt := range c.runtimes {
		if rt.channelID == res.ChannelID || rt.bridgeID == res.BridgeID || rt.externalMediaID == res.ExternalMediaID {
			if rt.echo != nil {
				_ = rt.echo.Stop(ctx)
			}
			delete(c.byChan, rt.channelID)
			delete(c.byChan, rt.externalMediaID)
			delete(c.runtimes, callID)
		}
	}
	return first
}

func (c *Client) Subscribe(ctx context.Context, handler ports.EventHandler) error {
	c.mu.Lock()
	c.handler = handler
	c.mu.Unlock()
	go c.wsLoop(ctx)
	return nil
}

func (c *Client) originate(ctx context.Context, endpoint string, req ports.StartCallRequest) (string, error) {
	q := url.Values{}
	q.Set("endpoint", endpoint)
	q.Set("app", c.app)
	q.Set("appArgs", strings.Join([]string{req.CallID, req.SessionID, req.AISessionID}, ","))
	q.Set("callerId", "Sirena Media <media>")
	q.Set("timeout", "30")

	resp, err := c.do(ctx, http.MethodPost, "/channels?"+q.Encode(), nil, nil)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("originate failed: %s", truncate(body))
	}
	var ch struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(body, &ch); err != nil {
		return "", err
	}
	return ch.ID, nil
}

func (c *Client) createBridge(ctx context.Context, callID string) (string, error) {
	q := url.Values{}
	q.Set("type", "mixing")
	q.Set("name", "sirena-"+callID)
	resp, err := c.do(ctx, http.MethodPost, "/bridges?"+q.Encode(), nil, nil)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("create bridge: %s", truncate(body))
	}
	var b struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(body, &b); err != nil {
		return "", err
	}
	return b.ID, nil
}

func (c *Client) destroyBridge(ctx context.Context, bridgeID string) error {
	resp, err := c.do(ctx, http.MethodDelete, "/bridges/"+url.PathEscape(bridgeID), nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 && resp.StatusCode != http.StatusNotFound {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("destroy bridge: %s", truncate(body))
	}
	return nil
}

func (c *Client) createExternalMedia(ctx context.Context, externalHost string) (string, error) {
	q := url.Values{}
	q.Set("app", c.app)
	q.Set("external_host", externalHost)
	q.Set("format", "ulaw")
	q.Set("encapsulation", "rtp")
	q.Set("transport", "udp")
	q.Set("connection_type", "client")
	q.Set("direction", "both")

	resp, err := c.do(ctx, http.MethodPost, "/channels/externalMedia?"+q.Encode(), nil, nil)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("externalMedia: %s", truncate(body))
	}
	var ch struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(body, &ch); err != nil {
		return "", err
	}
	return ch.ID, nil
}

func (c *Client) addToBridge(ctx context.Context, bridgeID, channelID string) error {
	resp, err := c.do(ctx, http.MethodPost, "/bridges/"+url.PathEscape(bridgeID)+"/addChannel?channel="+url.QueryEscape(channelID), nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("addChannel: %s", truncate(body))
	}
	return nil
}

func (c *Client) answer(ctx context.Context, channelID string) error {
	resp, err := c.do(ctx, http.MethodPost, "/channels/"+url.PathEscape(channelID)+"/answer", nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 && resp.StatusCode != http.StatusNotFound {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("answer: %s", truncate(body))
	}
	return nil
}

func (c *Client) hangupChannel(ctx context.Context, channelID string) error {
	resp, err := c.do(ctx, http.MethodDelete, "/channels/"+url.PathEscape(channelID), nil, nil)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode >= 300 && resp.StatusCode != http.StatusNotFound {
		body, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("hangup: %s", truncate(body))
	}
	return nil
}

func (c *Client) do(ctx context.Context, method, path string, body []byte, contentType *string) (*http.Response, error) {
	var rdr io.Reader
	if body != nil {
		rdr = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, rdr)
	if err != nil {
		return nil, err
	}
	req.SetBasicAuth(c.username, c.password)
	if contentType != nil {
		req.Header.Set("Content-Type", *contentType)
	}
	return c.http.Do(req)
}

func (c *Client) wsLoop(ctx context.Context) {
	backoff := time.Second
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		if err := c.wsOnce(ctx); err != nil {
			c.log.Warn("ari websocket disconnected", "err", err, "retryIn", backoff.String())
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < 30*time.Second {
			backoff *= 2
		}
	}
}

func (c *Client) wsOnce(ctx context.Context) error {
	u, err := url.Parse(c.baseURL)
	if err != nil {
		return err
	}
	scheme := "ws"
	if u.Scheme == "https" {
		scheme = "wss"
	}
	wsURL := url.URL{
		Scheme: scheme,
		Host:   u.Host,
		Path:   strings.TrimSuffix(u.Path, "/ari") + "/ari/events",
		RawQuery: url.Values{
			"app":           {c.app},
			"api_key":       {c.username + ":" + c.password},
			"subscribeAll":  {"false"},
		}.Encode(),
	}

	dialer := websocket.Dialer{HandshakeTimeout: 10 * time.Second}
	conn, _, err := dialer.DialContext(ctx, wsURL.String(), nil)
	if err != nil {
		return err
	}
	defer conn.Close()
	c.log.Info("ari websocket connected", "app", c.app)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		_ = conn.SetReadDeadline(time.Now().Add(60 * time.Second))
		_, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		c.handleWSMessage(ctx, data)
	}
}

func (c *Client) handleWSMessage(ctx context.Context, data []byte) {
	var raw map[string]any
	if err := json.Unmarshal(data, &raw); err != nil {
		return
	}
	typ, _ := raw["type"].(string)
	channelID := ""
	state := ""
	var args []string
	if ch, ok := raw["channel"].(map[string]any); ok {
		channelID, _ = ch["id"].(string)
		state, _ = ch["state"].(string)
	}
	if a, ok := raw["args"].([]any); ok {
		for _, v := range a {
			if s, ok := v.(string); ok {
				args = append(args, s)
			}
		}
	}

	switch typ {
	case "StasisStart":
		c.onStasisStart(ctx, channelID, args)
	case "ChannelStateChange":
		c.emit(ports.ARIEvent{Type: typ, ChannelID: channelID, State: state, Args: args})
	case "ChannelDestroyed", "StasisEnd":
		c.emit(ports.ARIEvent{Type: typ, ChannelID: channelID, State: state, Args: args})
	}
}

func (c *Client) onStasisStart(ctx context.Context, channelID string, args []string) {
	c.mu.Lock()
	callID, ok := c.byChan[channelID]
	var rt *callRuntime
	if ok {
		rt = c.runtimes[callID]
	}
	// External media channel also enters Stasis; already on bridge.
	isExt := rt != nil && rt.externalMediaID == channelID
	c.mu.Unlock()

	if isExt {
		return
	}

	if rt == nil && len(args) > 0 {
		callID = args[0]
		c.mu.Lock()
		rt = c.runtimes[callID]
		if rt != nil {
			rt.channelID = channelID
			c.byChan[channelID] = callID
		}
		c.mu.Unlock()
	}
	if rt == nil {
		c.log.Warn("stasis start for unknown channel", "channelId", channelID)
		return
	}

	_ = c.answer(ctx, channelID)
	if err := c.addToBridge(ctx, rt.bridgeID, channelID); err != nil {
		c.log.Error("add sip channel to bridge failed", "err", err, "callId", rt.callID, "channelId", channelID)
		c.emit(ports.ARIEvent{Type: "ChannelDestroyed", ChannelID: channelID, State: "Failed"})
		return
	}
	c.mu.Lock()
	rt.bridged = true
	c.mu.Unlock()

	c.emit(ports.ARIEvent{Type: "ChannelStateChange", ChannelID: channelID, State: "Up", Args: args})
}

func (c *Client) emit(evt ports.ARIEvent) {
	c.mu.Lock()
	h := c.handler
	c.mu.Unlock()
	if h != nil {
		h(evt)
	}
}

func truncate(b []byte) string {
	s := string(b)
	if len(s) > 256 {
		return s[:256]
	}
	return s
}
