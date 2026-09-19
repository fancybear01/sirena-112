package ari

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
	"github.com/gorilla/websocket"
)

type trackedEcho struct{ stopped bool }

func (*trackedEcho) Start(context.Context) error  { return nil }
func (e *trackedEcho) Stop(context.Context) error { e.stopped = true; return nil }
func (*trackedEcho) Stats() ports.RTPStats        { return ports.RTPStats{} }

type trackedFactory struct{ echo *trackedEcho }

func (f trackedFactory) Create(string, int) (ports.EchoSession, int, error) {
	return f.echo, 18000, nil
}

func TestStartRollbackAfterCancellation(t *testing.T) {
	for _, stage := range []string{"/ari/bridges", "/ari/channels/externalMedia", "/ari/bridges/call-bridge/addChannel", "/ari/channels"} {
		t.Run(stage, func(t *testing.T) {
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			var mu sync.Mutex
			deleted := map[string]bool{}
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method == http.MethodDelete {
					mu.Lock()
					deleted[r.URL.Path] = true
					mu.Unlock()
					w.WriteHeader(204)
					return
				}
				if r.URL.Path == stage {
					cancel()
					<-r.Context().Done()
					return
				}
				id := r.URL.Query().Get("channelId")
				if r.URL.Path == "/ari/bridges" {
					id = r.URL.Query().Get("bridgeId")
				}
				_ = json.NewEncoder(w).Encode(map[string]string{"id": id})
			}))
			defer srv.Close()
			echo := &trackedEcho{}
			c := NewClient(Config{BaseURL: srv.URL + "/ari", EchoFactory: trackedFactory{echo}, Log: slog.Default()})
			c.connected.Store(true)
			if _, err := c.StartCall(ctx, ports.StartCallRequest{CallID: "call", SIPAddress: "1001"}); err == nil {
				t.Fatal("expected cancelled start")
			}
			if !echo.stopped {
				t.Fatal("echo leaked")
			}
			mu.Lock()
			defer mu.Unlock()
			for _, path := range []string{"/ari/channels/call", "/ari/channels/call-media", "/ari/bridges/call-bridge"} {
				if !deleted[path] {
					t.Errorf("missing rollback %s", path)
				}
			}
		})
	}
}

func TestEarlyStasisAndExternalMediaFailure(t *testing.T) {
	var c *Client
	earlyDone := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := r.URL.Query().Get("channelId")
		switch r.URL.Path {
		case "/ari/bridges":
			id = r.URL.Query().Get("bridgeId")
		case "/ari/channels":
			if id != "call" {
				t.Errorf("originate ID=%q", id)
			}
			go func() {
				c.handleWSMessage(context.Background(), []byte(`{"type":"StasisStart","channel":{"id":"call"}}`))
				close(earlyDone)
			}()
		}
		_ = json.NewEncoder(w).Encode(map[string]string{"id": id})
	}))
	defer srv.Close()
	echo := &trackedEcho{}
	c = NewClient(Config{BaseURL: srv.URL + "/ari", RTPPublicHost: "::1", EchoFactory: trackedFactory{echo}, Log: slog.Default()})
	c.connected.Store(true)
	events := make(chan ports.ARIEvent, 4)
	c.handler = func(evt ports.ARIEvent) { events <- evt }
	res, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "call", SIPAddress: "1001"})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case <-earlyDone:
	case <-time.After(time.Second):
		t.Fatal("early Stasis blocked")
	}
	evt := <-events
	if evt.CallID != "call" || evt.State != "Up" {
		t.Fatalf("event=%+v", evt)
	}
	c.handleWSMessage(context.Background(), []byte(`{"type":"ChannelStateChange","channel":{"id":"call-media","state":"Up"}}`))
	c.handleWSMessage(context.Background(), []byte(`{"type":"StasisStart","channel":{"id":"call"}}`))
	if len(events) != 0 {
		t.Fatal("duplicate/early Up published")
	}
	c.handleWSMessage(context.Background(), []byte(`{"type":"StasisEnd","channel":{"id":"call-media"}}`))
	evt = <-events
	if evt.CallID != "call" || evt.State != "Failed" {
		t.Fatalf("external media loss ignored: %+v", evt)
	}
	if err := c.DestroyCall(context.Background(), res); err != nil {
		t.Fatal(err)
	}
	if !echo.stopped || len(c.runtimes) != 0 || len(c.byChan) != 0 {
		t.Fatal("resources leaked")
	}
}

func TestWebSocketCancellationAndHeaderAuth(t *testing.T) {
	upgraded := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, pass, ok := r.BasicAuth()
		if !ok || user != "media" || pass != "secret" || strings.Contains(r.URL.RawQuery, "secret") {
			t.Error("credentials must be in Authorization header")
		}
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		close(upgraded)
		for {
			if _, _, err := conn.ReadMessage(); err != nil {
				return
			}
		}
	}))
	defer srv.Close()
	c := NewClient(Config{BaseURL: srv.URL + "/ari", Username: "media", Password: "secret", App: "sirena-media", Log: slog.Default()})
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- c.wsOnce(ctx) }()
	<-upgraded
	cancel()
	select {
	case err := <-done:
		if err == nil {
			t.Fatal("expected closed connection")
		}
	case <-time.After(time.Second):
		t.Fatal("idle websocket did not stop")
	}
	if c.connected.Load() {
		t.Fatal("still ready after disconnect")
	}
}

func TestDisconnectTerminatesKnownCalls(t *testing.T) {
	c := NewClient(Config{Log: slog.Default()})
	rt := &callRuntime{callID: "call", channelID: "ch", events: make(chan ports.ARIEvent, 1), done: make(chan struct{}), overflow: make(chan struct{})}
	c.runtimes["call"] = rt
	c.failCalls()
	got := <-rt.events
	if got.CallID != "call" || got.Type != "ChannelDestroyed" || got.State != "Failed" {
		t.Fatalf("event=%+v", got)
	}
	if _, err := c.StartCall(context.Background(), ports.StartCallRequest{}); !errors.Is(err, domain.ErrARIUnavailable) {
		t.Fatalf("start without WS: %v", err)
	}
}
