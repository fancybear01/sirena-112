package rtp

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/gorilla/websocket"
)

func eventually(t *testing.T, f func() bool) {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if f() {
			return
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("condition timed out")
}

func TestAIHangupDrainsPlayback(t *testing.T) {
	peer, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	session, _, err := (&AIFactory{Log: slog.Default()}).Create("127.0.0.1", 0)
	if err != nil {
		t.Fatal(err)
	}
	s := session.(*AISession)
	events := make(chan ports.ARIEvent, 1)
	s.emit = func(e ports.ARIEvent) { events <- e }
	s.req.CallID = "last-phrase"
	s.peer = peer.LocalAddr().(*net.UDPAddr)
	s.completed = true
	for i := 0; i < 5; i++ {
		s.output <- bytes.Repeat([]byte{255}, 160)
	}
	if err := s.onEvent(map[string]any{"type": "caller.state_changed", "hangUp": true}); err != nil {
		t.Fatal(err)
	}
	select {
	case <-events:
		t.Fatal("hangup cut queued audio")
	default:
	}
	if err := s.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	defer s.Stop(context.Background())
	for i := 0; i < 5; i++ {
		peer.SetReadDeadline(time.Now().Add(time.Second))
		buf := make([]byte, 2048)
		if _, _, err := peer.ReadFromUDP(buf); err != nil {
			t.Fatal(err)
		}
	}
	select {
	case e := <-events:
		if e.Type != "StasisEnd" || e.CallID != "last-phrase" {
			t.Fatal(e)
		}
	case <-time.After(time.Second):
		t.Fatal("no hangup after last packet")
	}
}

func TestAIBridgeTwoTurnsAndRepeatedCall(t *testing.T) {
	var closed atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer c.Close()
		defer closed.Add(1)
		c.SetReadDeadline(time.Now().Add(5 * time.Second))
		_, b, err := c.ReadMessage()
		if err != nil {
			t.Error(err)
			return
		}
		var start map[string]any
		if json.Unmarshal(b, &start) != nil || start["type"] != "stream.start" || start["sessionId"] != "session" || start["aiSessionId"] != "ai" {
			t.Errorf("bad start: %s", b)
			return
		}
		format, ok := start["audio"].(map[string]any)
		if !ok || format["sampleRate"] != float64(16000) || format["channels"] != float64(1) || format["encoding"] != "pcm_s16le" {
			t.Error("bad audio format")
			return
		}
		for turn := 0; turn < 2; turn++ {
			// Real AI sends nothing for individual input frames.
			for i := 0; i < 3; i++ {
				k, b, err := c.ReadMessage()
				if err != nil || k != websocket.BinaryMessage || len(b) != 640 {
					t.Errorf("input: kind=%d bytes=%d err=%v", k, len(b), err)
					return
				}
			}
			_, b, err := c.ReadMessage()
			if err != nil || !bytes.Contains(b, []byte("input.flush")) {
				t.Errorf("flush: %s %v", b, err)
				return
			}
			for _, e := range []map[string]any{{"type": "transcript.final", "text": "fixture", "simulated": true, "startedAtMs": turn * 60, "endedAtMs": (turn + 1) * 60}, {"type": "response.started", "text": "reply"}} {
				if err := c.WriteJSON(e); err != nil {
					t.Error(err)
					return
				}
			}
			// A burst of five frames must become paced RTP, not a UDP burst.
			c.WriteMessage(websocket.BinaryMessage, make([]byte, 5*640))
			c.WriteJSON(map[string]any{"type": "response.completed", "durationMs": 100})
			c.WriteJSON(map[string]any{"type": "caller.state_changed", "hangUp": false})
		}
		_, b, err = c.ReadMessage()
		if err != nil || !bytes.Contains(b, []byte("stream.stop")) {
			t.Errorf("stop: %s %v", b, err)
		}
	}))
	defer srv.Close()
	for call := 0; call < 2; call++ {
		factory := &AIFactory{URL: "ws" + strings.TrimPrefix(srv.URL, "http"), Log: slog.Default()}
		session, port, err := factory.Create("127.0.0.1", 0)
		if err != nil {
			t.Fatal(err)
		}
		s := session.(*AISession)
		if err = s.Start(context.Background()); err != nil {
			t.Fatal(err)
		}
		defer s.Stop(context.Background())
		events := make(chan ports.ARIEvent, 8)
		if err = s.Activate(ports.StartCallRequest{CallID: "call", SessionID: "session", AISessionID: "ai"}, func(e ports.ARIEvent) { events <- e }); err != nil {
			t.Fatal(err)
		}
		peer, err := net.DialUDP("udp", nil, &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: port})
		if err != nil {
			t.Fatal(err)
		}
		var previous Packet
		var previousTime time.Time
		for turn := 0; turn < 2; turn++ {
			for i := 0; i < 3; i++ {
				raw, err := os.ReadFile("../../../../tests/voicefixture/testdata/0" + string(rune('0'+i)) + ".rtp")
				if err != nil {
					t.Fatal(err)
				}
				p, _ := Parse(raw)
				seq := uint16(turn*3 + i)
				peer.Write(Marshal(seq, uint32(seq)*160, 7, 0, false, p.Payload))
			}
			eventually(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.inputFrames == 3 })
			if err := s.Control("input.flush"); err != nil {
				t.Fatal(err)
			}
			select {
			case e := <-events:
				if e.Type != "transcript.final" {
					t.Fatalf("event=%+v", e)
				}
			case <-time.After(time.Second):
				t.Fatal("transcript missing")
			}
			for i := 0; i < 5; i++ {
				peer.SetReadDeadline(time.Now().Add(time.Second))
				buf := make([]byte, 2048)
				n, err := peer.Read(buf)
				if err != nil {
					t.Fatal(err)
				}
				now := time.Now()
				p, err := Parse(buf[:n])
				if err != nil {
					t.Fatal(err)
				}
				if len(p.Payload) != 160 || !bytes.Equal(p.Payload, bytes.Repeat([]byte{255}, 160)) {
					t.Fatal("scripted PCM should be RTP silence")
				}
				if !previousTime.IsZero() {
					if p.SequenceNumber != previous.SequenceNumber+1 || (i > 0 && p.Timestamp != previous.Timestamp+160) || p.SSRC != previous.SSRC {
						t.Fatal("RTP continuity")
					}
					if i > 0 && now.Sub(previousTime) < 10*time.Millisecond {
						t.Fatal("RTP burst instead of pacing")
					}
				}
				previous, previousTime = p, now
			}
			eventually(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return !s.waiting })
		}
		if err := s.Stop(context.Background()); err != nil {
			t.Fatal(err)
		}
		peer.Close()
		eventually(t, func() bool { return closed.Load() == int32(call+1) })
		conn, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: port})
		if err != nil {
			t.Fatalf("leaked UDP socket: %v", err)
		}
		conn.Close()
	}
}

func TestAIDisconnectAndPlaybackOverflow(t *testing.T) {
	for _, overflow := range []bool{false, true} {
		t.Run(map[bool]string{false: "disconnect", true: "overflow"}[overflow], func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				c, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
				if err != nil {
					return
				}
				defer c.Close()
				c.ReadMessage()
				if overflow {
					c.WriteMessage(websocket.BinaryMessage, make([]byte, 640*501))
					c.ReadMessage()
				}
			}))
			defer srv.Close()
			factory := &AIFactory{URL: "ws" + strings.TrimPrefix(srv.URL, "http"), Log: slog.Default()}
			sess, _, _ := factory.Create("127.0.0.1", 0)
			s := sess.(*AISession)
			s.Start(context.Background())
			defer s.Stop(context.Background())
			events := make(chan ports.ARIEvent, 2)
			s.mu.Lock()
			s.waiting = true
			s.mu.Unlock()
			if err := s.Activate(ports.StartCallRequest{CallID: "c"}, func(e ports.ARIEvent) { events <- e }); err != nil {
				t.Fatal(err)
			}
			select {
			case e := <-events:
				if e.Type != "media.error" {
					t.Fatal(e)
				}
			case <-time.After(2 * time.Second):
				t.Fatal("disconnect not reported")
			}
			s.Stop(context.Background())
		})
	}
}

func TestCancelDropsInFlightAudioUntilAcknowledged(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close()
		c.SetReadDeadline(time.Now().Add(3 * time.Second))
		c.ReadMessage()
		_, b, err := c.ReadMessage()
		if err != nil || !bytes.Contains(b, []byte("response.cancel")) {
			t.Error("cancel not sent")
			return
		}
		c.WriteMessage(websocket.BinaryMessage, make([]byte, 640))
		c.WriteJSON(map[string]any{"type": "response.completed", "cancelled": false})
		c.WriteMessage(websocket.BinaryMessage, make([]byte, 640))
		c.WriteJSON(map[string]any{"type": "response.completed", "cancelled": true})
		c.ReadMessage()
	}))
	defer srv.Close()
	sess, _, err := (&AIFactory{URL: "ws" + strings.TrimPrefix(srv.URL, "http"), Log: slog.Default()}).Create("127.0.0.1", 0)
	if err != nil {
		t.Fatal(err)
	}
	s := sess.(*AISession)
	s.Start(context.Background())
	defer s.Stop(context.Background())
	errors := make(chan ports.ARIEvent, 1)
	if err := s.Activate(ports.StartCallRequest{CallID: "cancel"}, func(e ports.ARIEvent) { errors <- e }); err != nil {
		t.Fatal(err)
	}
	s.mu.Lock()
	s.waiting = true
	s.output <- bytes.Repeat([]byte{1}, 160)
	s.mu.Unlock()
	if err := s.Control("response.cancel"); err != nil {
		t.Fatal(err)
	}
	eventually(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.completed && !s.waiting && !s.dropping })
	if len(s.output) != 0 {
		t.Fatal("cancelled audio leaked into next turn")
	}
	select {
	case e := <-errors:
		t.Fatalf("unexpected failure: %+v", e)
	default:
	}
	s.Stop(context.Background())
}
