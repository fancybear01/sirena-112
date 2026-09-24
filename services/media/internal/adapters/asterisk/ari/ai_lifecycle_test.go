package ari

import (
	"context"
	"encoding/json"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/rtp"
	"github.com/fancybear01/sirena-112/services/media/internal/application/call"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
	"github.com/gorilla/websocket"
)

type lifecycleEvents struct {
	mu     sync.Mutex
	events []domain.Event
}

func (p *lifecycleEvents) Publish(_ context.Context, e domain.Event) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.events = append(p.events, e)
	return nil
}
func TestAICallCleanupAndRestartWithoutProcessRestart(t *testing.T) {
	connected := make(chan *websocket.Conn, 3)
	aiServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			return
		}
		defer c.Close()
		_, _, err = c.ReadMessage()
		if err != nil {
			return
		}
		connected <- c
		for {
			_, _, err = c.ReadMessage()
			if err != nil {
				return
			}
		}
	}))
	defer aiServer.Close()
	var mu sync.Mutex
	deleted := map[string]int{}
	ariServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method == http.MethodDelete {
			mu.Lock()
			deleted[r.URL.Path]++
			mu.Unlock()
			w.WriteHeader(204)
			return
		}
		json.NewEncoder(w).Encode(map[string]string{"id": r.URL.Query().Get("channelId")})
	}))
	defer ariServer.Close()
	listener, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1")})
	if err != nil {
		t.Fatal(err)
	}
	port := listener.LocalAddr().(*net.UDPAddr).Port
	listener.Close()
	client := NewClient(Config{BaseURL: ariServer.URL + "/ari", RTPListenHost: "127.0.0.1", RTPPublicHost: "127.0.0.1", RTPPort: port, RTPPortEnd: port, Log: slog.Default(), EchoFactory: &rtp.AIFactory{URL: "ws" + strings.TrimPrefix(aiServer.URL, "http"), Log: slog.Default()}})
	sink := &lifecycleEvents{}
	svc := call.NewService(client, sink, slog.Default())
	client.handler = svc.HandleARIEvent
	client.connected.Store(true)
	defer svc.Shutdown(context.Background())
	wait := func(f func() bool) {
		t.Helper()
		until := time.Now().Add(3 * time.Second)
		for time.Now().Before(until) {
			if f() {
				return
			}
			time.Sleep(time.Millisecond)
		}
		t.Fatal("cleanup/activation timeout")
	}
	for i := 0; i < 3; i++ {
		c, err := svc.Start(context.Background(), call.StartCommand{SessionID: "session", AISessionID: "ai", SIPAddress: "1001"})
		if err != nil {
			t.Fatal(err)
		}
		b, _ := json.Marshal(map[string]any{"type": "StasisStart", "channel": map[string]any{"id": c.AsteriskChannelID}})
		client.handleWSMessage(context.Background(), b)
		var conn *websocket.Conn
		select {
		case conn = <-connected:
		case <-time.After(time.Second):
			t.Fatal("AI not connected")
		}
		wait(func() bool { got, err := svc.Get(c.ID); return err == nil && got.State == domain.CallStateActive })
		if i == 1 {
			conn.Close()
		} else {
			if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID}); err != nil {
				t.Fatal(err)
			}
		}
		wait(func() bool {
			client.mu.Lock()
			defer client.mu.Unlock()
			return len(client.runtimes) == 0 && len(client.reserved) == 0
		})
		wait(func() bool { _, err := svc.Get(c.ID); return err != nil })
		mu.Lock()
		for _, path := range []string{"/ari/channels/" + c.AsteriskChannelID, "/ari/channels/" + c.ExternalMediaID, "/ari/bridges/" + c.BridgeID} {
			if deleted[path] != 1 {
				t.Errorf("cleanup %s count=%d", path, deleted[path])
			}
		}
		mu.Unlock()
	}
	sink.mu.Lock()
	defer sink.mu.Unlock()
	ended, failures := 0, 0
	for _, e := range sink.events {
		if e.Payload["callId"] == nil || e.Payload["aiSessionId"] != "ai" {
			t.Fatal("missing correlation")
		}
		if e.Type == domain.EventCallEnded {
			ended++
		}
		if e.Type == domain.EventMediaError {
			failures++
		}
	}
	if ended != 3 || failures != 1 {
		t.Fatalf("ended=%d failures=%d", ended, failures)
	}
}
