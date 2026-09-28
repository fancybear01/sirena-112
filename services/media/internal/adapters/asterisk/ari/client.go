package ari

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
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
	rtpPortEnd    int
	echoFactory   ports.EchoFactory

	connected  atomic.Bool
	mu         sync.Mutex
	handler    ports.EventHandler
	runtimes   map[string]*callRuntime // key: callID
	reserved   map[int]bool
	recordings map[string]recordingResult
	byChan     map[string]string // channelID -> callID
}

type recordingResult struct {
	info *ports.RecordingInfo
	err  error
}

type callRuntime struct {
	mu              sync.Mutex
	port            int
	stopped         bool
	ready           chan struct{}
	done            chan struct{}
	stopOnce        sync.Once
	overflow        chan struct{}
	overflowOnce    sync.Once
	events          chan ports.ARIEvent
	callID          string
	sessionID       string
	aiSessionID     string
	echo            ports.EchoSession
	bridgeID        string
	externalMediaID string
	channelID       string
	externalBridged bool
	sipBridged      bool
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
	RTPPortEnd    int
	EchoFactory   ports.EchoFactory
	Log           *slog.Logger
}

func NewClient(cfg Config) *Client {
	if cfg.RTPPort == 0 {
		cfg.RTPPort = 18000
	}
	if cfg.RTPPortEnd == 0 {
		cfg.RTPPortEnd = cfg.RTPPort
	}
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
		rtpPortEnd:    cfg.RTPPortEnd,
		reserved:      map[int]bool{},
		recordings:    map[string]recordingResult{},
		echoFactory:   cfg.EchoFactory,
		runtimes:      map[string]*callRuntime{},
		byChan:        map[string]string{},
	}
}

func (c *Client) Ready(ctx context.Context) error {
	if !c.connected.Load() {
		return domain.ErrARIUnavailable
	}
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

// A nonempty result on error means rollback failed: the caller must retain the
// IDs and retry DestroyCall. Ports remain reserved until remote cleanup succeeds.
func (c *Client) StartCall(ctx context.Context, req ports.StartCallRequest) (result ports.CallResources, startErr error) {
	if !c.connected.Load() {
		return result, domain.ErrARIUnavailable
	}
	echo, port, err := c.allocateEcho()
	if err != nil {
		return result, err
	}
	rt := &callRuntime{callID: req.CallID, sessionID: req.SessionID, aiSessionID: req.AISessionID,
		echo: echo, port: port, channelID: req.CallID, bridgeID: req.CallID + "-bridge", externalMediaID: "media-" + req.CallID,
		ready: make(chan struct{}), done: make(chan struct{}), overflow: make(chan struct{}), events: make(chan ports.ARIEvent, 64)}
	res := ports.CallResources{ChannelID: rt.channelID, BridgeID: rt.bridgeID, ExternalMediaID: rt.externalMediaID}
	// Publish IDs before ARI can send events, but gate this call's worker on ready.
	rt.mu.Lock()
	c.mu.Lock()
	_, exists := c.runtimes[req.CallID]
	if exists || !c.connected.Load() {
		delete(c.reserved, port)
		c.mu.Unlock()
		rt.mu.Unlock()
		_ = echo.Stop(context.Background())
		if exists {
			return result, domain.ErrCallExists
		}
		return result, domain.ErrARIUnavailable
	}
	c.runtimes[req.CallID] = rt
	c.byChan[rt.channelID], c.byChan[rt.externalMediaID] = req.CallID, req.CallID
	c.mu.Unlock()
	go c.runEvents(rt)
	defer func() {
		if startErr != nil {
			rt.stopped = true
			rt.stopOnce.Do(func() { close(rt.done) })
			cleanupCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			_ = echo.Stop(cleanupCtx)
			if cleanupErr := c.cleanup(cleanupCtx, res); cleanupErr != nil {
				result = res
				startErr = errors.Join(startErr, fmt.Errorf("start rollback: %w", cleanupErr))
				c.log.Error("start rollback pending", "callId", req.CallID, "err", cleanupErr)
			} else {
				c.forget(rt)
			}
		}
		rt.mu.Unlock()
		close(rt.ready)
	}()
	if err := echo.Start(context.Background()); err != nil {
		return result, err
	}
	if _, err := c.createBridge(ctx, req.CallID); err != nil {
		return result, err
	}
	extHost := net.JoinHostPort(c.rtpPublicHost, strconv.Itoa(port))
	actualExternalMediaID, err := c.createExternalMedia(ctx, extHost, res.ExternalMediaID)
	if err != nil {
		return result, err
	}
	c.log.Info("ari external media created", "callId", req.CallID, "requestedChannelId", res.ExternalMediaID, "channelId", actualExternalMediaID)
	endpoint := req.SIPAddress
	if !strings.Contains(endpoint, "/") {
		endpoint = "PJSIP/" + endpoint
	}
	if _, err := c.originate(ctx, endpoint, req); err != nil {
		return result, err
	}
	c.log.Info("ari call started", "callId", req.CallID, "sessionId", req.SessionID, "channelId", res.ChannelID, "rtpHost", extHost)
	return res, nil
}

func (c *Client) allocateEcho() (ports.EchoSession, int, error) {
	for port := c.rtpPort; port <= c.rtpPortEnd; port++ {
		c.mu.Lock()
		busy := c.reserved[port]
		if !busy {
			c.reserved[port] = true
		}
		c.mu.Unlock()
		if busy {
			continue
		}
		echo, bound, err := c.echoFactory.Create(c.rtpListenHost, port)
		if err == nil {
			return echo, bound, nil
		}
		c.mu.Lock()
		delete(c.reserved, port)
		c.mu.Unlock()
		if !errors.Is(err, syscall.EADDRINUSE) {
			return nil, 0, fmt.Errorf("rtp listen: %w", err)
		}
	}
	return nil, 0, domain.ErrCapacityExhausted
}

// Called with rt.mu held. No network or callback runs under the registry lock.
func (c *Client) forget(rt *callRuntime) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.runtimes[rt.callID] != rt {
		return
	}
	delete(c.byChan, rt.channelID)
	delete(c.byChan, rt.externalMediaID)
	delete(c.runtimes, rt.callID)
	delete(c.reserved, rt.port)
}

func (c *Client) Hangup(ctx context.Context, channelID string) error {
	return c.hangupChannel(ctx, channelID)
}

func (c *Client) DestroyCall(ctx context.Context, res ports.CallResources) error {
	c.mu.Lock()
	rt := c.runtimes[c.byChan[res.ChannelID]]
	c.mu.Unlock()
	if rt == nil {
		return c.cleanup(ctx, res)
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	rt.stopped = true
	rt.stopOnce.Do(func() { close(rt.done) })
	if rt.echo != nil {
		_ = rt.echo.Stop(ctx)
		if source, ok := rt.echo.(ports.RecordingSession); ok {
			info, err := source.Recording()
			c.mu.Lock()
			c.recordings[rt.callID] = recordingResult{info, err}
			c.mu.Unlock()
		}
	}
	if err := c.cleanup(ctx, res); err != nil {
		return err
	}
	c.forget(rt)
	return nil
}

func (c *Client) TakeRecording(callID string) (*ports.RecordingInfo, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	result := c.recordings[callID]
	delete(c.recordings, callID)
	return result.info, result.err
}

func (c *Client) cleanup(ctx context.Context, res ports.CallResources) error {
	var errs []error
	if res.ChannelID != "" {
		errs = append(errs, c.hangupChannel(ctx, res.ChannelID))
	}
	if res.ExternalMediaID != "" {
		errs = append(errs, c.hangupChannel(ctx, res.ExternalMediaID))
	}
	if res.BridgeID != "" {
		errs = append(errs, c.destroyBridge(ctx, res.BridgeID))
	}
	return errors.Join(errs...)
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
	q.Set("channelId", req.CallID)
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
	q.Set("bridgeId", callID+"-bridge")
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

func (c *Client) createExternalMedia(ctx context.Context, externalHost, channelID string) (string, error) {
	q := url.Values{}
	q.Set("app", c.app)
	q.Set("external_host", externalHost)
	q.Set("channelId", channelID)
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
			if ctx.Err() != nil {
				return
			}
			c.log.Warn("ari websocket disconnected", "err", err, "retryIn", backoff.String())
			c.failCalls()
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < 30*time.Second {
			backoff *= 2
			if backoff > 30*time.Second {
				backoff = 30 * time.Second
			}
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
			"app":          {c.app},
			"subscribeAll": {"false"},
		}.Encode(),
	}

	dialer := websocket.Dialer{HandshakeTimeout: 10 * time.Second}
	auth, _ := http.NewRequest(http.MethodGet, c.baseURL, nil)
	auth.SetBasicAuth(c.username, c.password)
	conn, resp, err := dialer.DialContext(ctx, wsURL.String(), auth.Header)
	if resp != nil && resp.Body != nil {
		defer resp.Body.Close()
	}
	if err != nil {
		return err
	}
	defer conn.Close()
	c.connected.Store(true)
	defer c.connected.Store(false)
	stopClose := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stopClose()
	conn.SetReadLimit(1 << 20)
	_ = conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	conn.SetPongHandler(func(string) error { return conn.SetReadDeadline(time.Now().Add(60 * time.Second)) })
	heartbeatCtx, stopHeartbeat := context.WithCancel(ctx)
	defer stopHeartbeat()
	go func() {
		ticker := time.NewTicker(20 * time.Second)
		defer ticker.Stop()
		for {
			select {
			case <-heartbeatCtx.Done():
				return
			case <-ticker.C:
				if err := conn.WriteControl(websocket.PingMessage, nil, time.Now().Add(5*time.Second)); err != nil {
					_ = conn.Close()
					return
				}
			}
		}
	}()
	c.log.Info("ari websocket connected", "app", c.app)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		_, data, err := conn.ReadMessage()
		if err != nil {
			return err
		}
		c.handleWSMessage(ctx, data)
	}
}

// Events may be lost across a reconnect. Fail closed instead of keeping stale calls.
func (c *Client) failCalls() {
	c.mu.Lock()
	events := make([]ports.ARIEvent, 0, len(c.runtimes))
	for _, rt := range c.runtimes {
		events = append(events, ports.ARIEvent{CallID: rt.callID, ChannelID: rt.channelID, Type: "ChannelDestroyed", State: "Failed"})
	}
	c.mu.Unlock()
	for _, evt := range events {
		c.enqueue(evt)
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
		c.enqueue(ports.ARIEvent{Type: typ, ChannelID: channelID, Args: args})
	case "ChannelStateChange":
		if state == "Up" {
			return
		}
		c.enqueue(ports.ARIEvent{Type: typ, ChannelID: channelID, State: state, Args: args})
	case "ChannelDestroyed", "StasisEnd":
		c.enqueue(ports.ARIEvent{Type: typ, ChannelID: channelID, State: state, Args: args})
	}
}

// The WebSocket reader only enqueues: a slow call cannot stall heartbeats or
// other calls. Each worker preserves ordering, with bounded memory per call.
func (c *Client) enqueue(evt ports.ARIEvent) {
	c.mu.Lock()
	if evt.CallID == "" {
		evt.CallID = c.byChan[evt.ChannelID]
	}
	rt := c.runtimes[evt.CallID]
	c.mu.Unlock()
	if rt == nil {
		return
	}
	select {
	case <-rt.done:
		return
	default:
	}
	select {
	case rt.events <- evt:
	case <-rt.done:
	default:
		rt.overflowOnce.Do(func() { close(rt.overflow) })
	}
}

func (c *Client) runEvents(rt *callRuntime) {
	select {
	case <-rt.ready:
	case <-rt.done:
		return
	}
	for {
		select {
		case <-rt.done:
			return
		case <-rt.overflow:
			c.emit(ports.ARIEvent{CallID: rt.callID, ChannelID: rt.channelID, Type: "ChannelDestroyed", State: "Failed"})
			return
		case evt := <-rt.events:
			rt.mu.Lock()
			if rt.stopped {
				rt.mu.Unlock()
				return
			}
			if evt.Type == "StasisStart" {
				isExternal := evt.ChannelID == rt.externalMediaID
				if (isExternal && rt.externalBridged) || (!isExternal && rt.sipBridged) {
					rt.mu.Unlock()
					continue
				}
				ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				channelID := rt.channelID
				if isExternal {
					channelID = rt.externalMediaID
				}
				err := c.addToBridge(ctx, rt.bridgeID, channelID)
				cancel()
				if isExternal {
					rt.externalBridged = err == nil
				} else {
					rt.sipBridged = err == nil
				}
				if isExternal && err == nil {
					rt.mu.Unlock()
					continue
				}
				evt.Type, evt.State = "ChannelStateChange", "Up"
				if err != nil {
					c.log.Error("add channel to bridge failed", "callId", rt.callID, "channelId", channelID, "err", err)
					evt.Type, evt.State = "media.error", "Failed"
					evt.Payload = map[string]any{"message": "could not add channel to call bridge"}
				}
			}
			var voice ports.VoiceSession
			if evt.Type == "ChannelStateChange" && evt.State == "Up" {
				voice, _ = rt.echo.(ports.VoiceSession)
			}
			req := ports.StartCallRequest{CallID: rt.callID, SessionID: rt.sessionID, AISessionID: rt.aiSessionID}
			rt.mu.Unlock()
			c.emit(evt)
			// No ARI runtime lock during handshake: hangup can cancel it immediately.
			if voice != nil {
				if err := voice.Activate(req, c.enqueue); err != nil {
					c.enqueue(ports.ARIEvent{CallID: rt.callID, Type: "media.error", Payload: map[string]any{"message": "AI stream activation failed"}})
				}
			}
		}
	}
}

func (c *Client) emit(evt ports.ARIEvent) {
	c.mu.Lock()
	if evt.CallID == "" {
		evt.CallID = c.byChan[evt.ChannelID]
	}
	if rt := c.runtimes[evt.CallID]; rt != nil && evt.ChannelID == rt.externalMediaID {
		if evt.Type != "ChannelDestroyed" && evt.Type != "StasisEnd" {
			c.mu.Unlock()
			return
		}
		evt.State = "Failed"
	}
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

func (c *Client) Control(ctx context.Context, callID, typ string) error {
	c.mu.Lock()
	rt := c.runtimes[callID]
	c.mu.Unlock()
	if rt == nil {
		return domain.ErrCallNotFound
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	if rt.stopped {
		return domain.ErrCallNotFound
	}
	voice, ok := rt.echo.(ports.VoiceSession)
	if !ok {
		return domain.ErrNotImplemented
	}
	if err := voice.Control(typ); err != nil {
		return fmt.Errorf("%w: %v", domain.ErrInvalidArgument, err)
	}
	return nil
}
