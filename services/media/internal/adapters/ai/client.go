package ai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/gorilla/websocket"
)

var ErrBackpressure = errors.New("AI write queue full")

type Config struct {
	BaseURL string
	Queue   int
	Timeout time.Duration
}
type message struct {
	kind int
	data []byte
}
type Client struct {
	conn     *websocket.Conn
	queue    chan message
	stop     chan chan struct{}
	ctx      context.Context
	cancel   context.CancelFunc
	wg       sync.WaitGroup
	once     sync.Once
	closing  atomic.Bool
	failures chan error
	done     chan struct{}
	timeout  time.Duration
}

func Dial(ctx context.Context, cfg Config, sessionID, aiID string, onAudio func([]byte) error, onEvent func(map[string]any) error, onError func(error)) (*Client, error) {
	if cfg.Queue <= 0 {
		cfg.Queue = 64
	}
	if cfg.Timeout <= 0 {
		cfg.Timeout = 3 * time.Second
	}
	base := strings.TrimRight(cfg.BaseURL, "/")
	endpoint := base + "/internal/v1/voice/" + url.PathEscape(aiID) + "?" + url.Values{"sessionId": {sessionID}}.Encode()
	conn, resp, err := (&websocket.Dialer{HandshakeTimeout: cfg.Timeout}).DialContext(ctx, endpoint, nil)
	if resp != nil && resp.Body != nil {
		defer resp.Body.Close()
	}
	if err != nil {
		return nil, fmt.Errorf("AI handshake: %w", err)
	}
	start := map[string]any{"type": "stream.start", "sessionId": sessionID, "aiSessionId": aiID, "audio": map[string]any{"encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1, "frameDurationMs": 20}}
	_ = conn.SetWriteDeadline(time.Now().Add(cfg.Timeout))
	if err := conn.WriteJSON(start); err != nil {
		conn.Close()
		return nil, err
	}
	lifetime, cancel := context.WithCancel(ctx)
	c := &Client{conn: conn, queue: make(chan message, cfg.Queue), stop: make(chan chan struct{}, 1), ctx: lifetime, cancel: cancel, failures: make(chan error, 1), done: make(chan struct{}), timeout: cfg.Timeout}
	conn.SetReadLimit(1 << 20)
	_ = conn.SetReadDeadline(time.Now().Add(60 * time.Second))
	conn.SetPongHandler(func(string) error { return conn.SetReadDeadline(time.Now().Add(60 * time.Second)) })
	c.wg.Add(2)
	go c.write()
	go func() {
		defer c.wg.Done()
		for {
			kind, b, err := conn.ReadMessage()
			if err != nil {
				c.fail(errors.New("AI websocket disconnected"))
				return
			}
			switch kind {
			case websocket.BinaryMessage:
				if len(b) == 0 || len(b)%2 != 0 {
					c.fail(errors.New("AI PCM must contain whole PCM16 samples"))
					return
				}
				err = onAudio(b)
			case websocket.TextMessage:
				var event map[string]any
				if json.Unmarshal(b, &event) != nil {
					c.fail(errors.New("invalid AI JSON"))
					return
				}
				err = onEvent(event)
			}
			if err != nil {
				c.fail(err)
				return
			}
		}
	}()
	go func() {
		select {
		case err := <-c.failures:
			if !c.closing.Load() {
				c.Close()
				onError(err)
			}
		case <-lifetime.Done():
			c.Close()
		case <-c.done:
		}
	}()
	return c, nil
}
func (c *Client) fail(err error) {
	select {
	case c.failures <- err:
	default:
	}
}
func (c *Client) SendPCM(b []byte) error {
	if len(b) != 640 {
		return errors.New("input PCM frame must be 640 bytes")
	}
	return c.send(message{websocket.BinaryMessage, append([]byte(nil), b...)})
}
func (c *Client) Control(typ string) error {
	if typ != "input.flush" && typ != "response.cancel" {
		return errors.New("unsupported AI command")
	}
	b, _ := json.Marshal(map[string]any{"type": typ})
	return c.send(message{websocket.TextMessage, b})
}
func (c *Client) send(m message) error {
	if c.closing.Load() {
		return errors.New("AI stream closed")
	}
	select {
	case <-c.ctx.Done():
		return c.ctx.Err()
	case c.queue <- m:
		return nil
	default:
		c.fail(ErrBackpressure)
		return ErrBackpressure
	}
}
func (c *Client) write() {
	defer c.wg.Done()
	ticker := time.NewTicker(20 * time.Second)
	defer ticker.Stop()
	write := func(m message) error {
		_ = c.conn.SetWriteDeadline(time.Now().Add(c.timeout))
		return c.conn.WriteMessage(m.kind, m.data)
	}
	for {
		// Stop has priority over queued audio.
		select {
		case ack := <-c.stop:
			_ = write(message{websocket.TextMessage, []byte(`{"type":"stream.stop"}`)})
			close(ack)
			return
		default:
		}
		select {
		case <-c.ctx.Done():
			return
		case ack := <-c.stop:
			_ = write(message{websocket.TextMessage, []byte(`{"type":"stream.stop"}`)})
			close(ack)
			return
		case m := <-c.queue:
			if err := write(m); err != nil {
				c.fail(errors.New("AI websocket write failed"))
				return
			}
		case <-ticker.C:
			if err := c.conn.WriteControl(websocket.PingMessage, nil, time.Now().Add(c.timeout)); err != nil {
				c.fail(errors.New("AI ping failed"))
				return
			}
		}
	}
}

// Close bounds best-effort stream.stop even when a writer is stalled.
func (c *Client) Close() {
	c.once.Do(func() {
		c.closing.Store(true)
		ack := make(chan struct{})
		c.stop <- ack
		select {
		case <-ack:
		case <-time.After(300 * time.Millisecond):
		}
		c.cancel()
		c.conn.Close()
		c.wg.Wait()
		close(c.done)
	})
}
func (c *Client) Done() <-chan struct{} { return c.done }
