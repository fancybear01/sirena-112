package voicefixture

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/rtp"
	"github.com/gorilla/websocket"
)

type message struct {
	kind int
	data []byte
}
type socket interface {
	ReadMessage() (int, []byte, error)
	WriteMessage(int, []byte) error
	Close() error
}

// Test-only transport model for the #53 acceptance boundary, not a live adapter.
type stream struct {
	conn     socket
	queue    chan message
	received chan message
	abort    chan struct{}
	done     chan struct{}
	once     sync.Once
}

var errQueueFull = errors.New("audio queue full")

func newStream(conn socket) *stream {
	s := &stream{conn: conn, queue: make(chan message, 2), received: make(chan message, 8), abort: make(chan struct{}), done: make(chan struct{})}
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		for {
			select {
			case <-s.abort:
				return
			case m := <-s.queue:
				if err := conn.WriteMessage(m.kind, m.data); err != nil {
					s.close()
					return
				}
			}
		}
	}()
	go func() {
		defer wg.Done()
		for {
			k, b, err := conn.ReadMessage()
			if err != nil {
				s.close()
				return
			}
			select {
			case s.received <- message{k, b}:
			case <-s.abort:
				return
			default:
				s.close()
				return
			}
		}
	}()
	go func() { wg.Wait(); close(s.done) }()
	return s
}
func (s *stream) close() { s.once.Do(func() { close(s.abort); _ = s.conn.Close() }) }
func (s *stream) send(m message) error {
	select {
	case <-s.abort:
		return errors.New("stream closed")
	default:
	}
	select {
	case s.queue <- message{m.kind, bytes.Clone(m.data)}:
		return nil
	case <-s.abort:
		return errors.New("stream closed")
	default:
		return errQueueFull
	}
}
func await(t *testing.T, ch <-chan struct{}) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(2 * time.Second):
		t.Fatal("connection/worker leaked or operation blocked")
	}
}
func receive(t *testing.T, s *stream) message {
	t.Helper()
	select {
	case m := <-s.received:
		return m
	case <-time.After(2 * time.Second):
		t.Fatal("response timeout")
		return message{}
	}
}
func send(t *testing.T, s *stream, m message) {
	t.Helper()
	if err := s.send(m); err != nil {
		t.Fatal(err)
	}
}

var start = message{websocket.TextMessage, []byte(`{"type":"stream.start","sessionId":"fixture-session","aiSessionId":"fixture-ai","audio":{"encoding":"pcm_s16le","sampleRate":16000,"channels":1,"frameDurationMs":20}}`)}

func TestFakeAIRoundTrip(t *testing.T) {
	inputs := [][]byte{fixture(t, 0, "pcm"), fixture(t, 1, "pcm"), fixture(t, 2, "pcm")}
	finished := make(chan struct{})
	serverErr := make(chan error, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer close(finished)
		if r.URL.Path != "/internal/v1/voice/fixture-ai" || r.URL.Query().Get("sessionId") != "fixture-session" {
			serverErr <- errors.New("wrong session URL")
			http.Error(w, "wrong session", 400)
			return
		}
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			serverErr <- err
			return
		}
		defer conn.Close()
		_ = conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		read := func(want message) error {
			k, b, err := conn.ReadMessage()
			if err != nil {
				return err
			}
			if k != want.kind {
				return fmt.Errorf("message kind=%d", k)
			}
			if k == websocket.TextMessage {
				var got, expected any
				if json.Unmarshal(b, &got) != nil || json.Unmarshal(want.data, &expected) != nil {
					return errors.New("invalid JSON")
				}
				a, _ := json.Marshal(got)
				z, _ := json.Marshal(expected)
				if !bytes.Equal(a, z) {
					return fmt.Errorf("control mismatch: %s", b)
				}
			} else if !bytes.Equal(b, want.data) {
				return errors.New("binary frame reordered/changed")
			}
			return nil
		}
		if err := read(start); err != nil {
			serverErr <- err
			return
		}
		// Acknowledgements are fixture synchronization only, not an added AI protocol.
		for _, pcm := range inputs {
			if err := read(message{websocket.BinaryMessage, pcm}); err != nil {
				serverErr <- err
				return
			}
			if err := conn.WriteMessage(websocket.TextMessage, []byte(`{"type":"transcript.partial","text":"fixture"}`)); err != nil {
				serverErr <- err
				return
			}
		}
		if err := read(message{websocket.TextMessage, []byte(`{"type":"input.flush","sequence":3,"timestamp":"2026-09-23T00:00:00Z"}`)}); err != nil {
			serverErr <- err
			return
		}
		for _, pcm := range inputs {
			if err := conn.WriteMessage(websocket.BinaryMessage, pcm); err != nil {
				serverErr <- err
				return
			}
		}
		if err := read(message{websocket.TextMessage, []byte(`{"type":"stream.stop"}`)}); err != nil {
			serverErr <- err
			return
		}
		_ = conn.WriteControl(websocket.CloseMessage, websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""), time.Now().Add(time.Second))
		_, _, err = conn.ReadMessage()
		if !websocket.IsCloseError(err, websocket.CloseNormalClosure) {
			serverErr <- fmt.Errorf("no normal close acknowledgement: %v", err)
			return
		}
		serverErr <- nil
	}))
	defer srv.Close()
	conn, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(srv.URL, "http")+"/internal/v1/voice/fixture-ai?sessionId=fixture-session", nil)
	if err != nil {
		t.Fatal(err)
	}
	s := newStream(conn)
	defer s.close()
	send(t, s, start)
	for i := 0; i < 3; i++ {
		p, err := rtp.Parse(fixture(t, i, "rtp"))
		if err != nil {
			t.Fatal(err)
		}
		send(t, s, message{websocket.BinaryMessage, toPCM16k(p.Payload)})
		if m := receive(t, s); m.kind != websocket.TextMessage {
			t.Fatal("expected transcript metadata")
		}
	}
	send(t, s, message{websocket.TextMessage, []byte(`{"type":"input.flush","sequence":3,"timestamp":"2026-09-23T00:00:00Z"}`)})
	for i := 0; i < 3; i++ {
		m := receive(t, s)
		if m.kind != websocket.BinaryMessage || len(m.data) != 640 || !bytes.Equal(m.data, inputs[i]) {
			t.Fatalf("response frame %d", i)
		}
		p, _ := rtp.Parse(fixture(t, i, "rtp"))
		if !bytes.Equal(toULAW(m.data), p.Payload) {
			t.Fatalf("return RTP frame %d", i)
		}
	}
	send(t, s, message{websocket.TextMessage, []byte(`{"type":"stream.stop"}`)})
	await(t, s.done)
	await(t, finished)
	if err := <-serverErr; err != nil {
		t.Fatal(err)
	}
}

// Hold a write deterministically: TCP buffering cannot make this queue test flaky.
type heldSocket struct {
	*websocket.Conn
	entered   chan struct{}
	closed    chan struct{}
	once      sync.Once
	closeOnce sync.Once
}

func (c *heldSocket) WriteMessage(int, []byte) error {
	c.once.Do(func() { close(c.entered) })
	<-c.closed
	return errors.New("disconnected")
}
func (c *heldSocket) Close() error { c.closeOnce.Do(func() { close(c.closed) }); return c.Conn.Close() }
func TestQueueBoundAndSingleDisconnect(t *testing.T) {
	cut := make(chan struct{})
	finished := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer close(finished)
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		<-cut
		_ = conn.Close() // one abrupt peer disconnect
	}))
	defer srv.Close()
	var cutOnce sync.Once
	disconnect := func() { cutOnce.Do(func() { close(cut) }) }
	defer disconnect()
	conn, _, err := websocket.DefaultDialer.Dial("ws"+strings.TrimPrefix(srv.URL, "http"), nil)
	if err != nil {
		t.Fatal(err)
	}
	held := &heldSocket{Conn: conn, entered: make(chan struct{}), closed: make(chan struct{})}
	s := newStream(held)
	defer s.close()
	send(t, s, start)
	await(t, held.entered)
	frame := message{websocket.BinaryMessage, fixture(t, 1, "pcm")}
	send(t, s, frame)
	send(t, s, frame)
	progress := make(chan struct{})
	raw := fixture(t, 1, "rtp")
	go func() {
		defer close(progress)
		if !errors.Is(s.send(frame), errQueueFull) {
			t.Error("queue must reject the third waiting frame")
		}
		if _, err := rtp.Parse(raw); err != nil {
			t.Error(err)
		}
	}()
	await(t, progress) // producer can continue processing RTP while AI writer is stuck
	if len(s.queue) != 2 {
		t.Fatalf("queue exceeded its bound: %d", len(s.queue))
	}
	disconnect()
	await(t, s.done)
	await(t, finished)
	if err := s.send(frame); err == nil {
		t.Fatal("accepted frame after disconnect")
	}
}
