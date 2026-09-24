package core

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

func TestPublisherRetryKeepsIdentityAndOrder(t *testing.T) {
	var mu sync.Mutex
	var bodies [][]byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/internal/v1/media/events" {
			t.Error(r.URL.Path)
		}
		b, _ := io.ReadAll(r.Body)
		mu.Lock()
		bodies = append(bodies, b)
		n := len(bodies)
		mu.Unlock()
		if n == 1 {
			w.WriteHeader(503)
		} else {
			w.Write([]byte(`{"accepted":false}`))
		}
	}))
	defer srv.Close()
	p := NewHTTPPublisher(srv.URL, slog.Default())
	payload := map[string]any{"callId": "call", "aiSessionId": "ai"}
	event := domain.Event{EventID: "fixed", SessionID: "session", Type: "call.answered", Timestamp: time.Now().UTC(), Source: "media", Payload: payload}
	if err := p.Publish(context.Background(), event); err != nil {
		t.Fatal(err)
	}
	payload["callId"] = "mutated"
	event.EventID = "ended"
	event.Type = "call.ended"
	p.Publish(context.Background(), event)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if err := p.Close(ctx); err != nil {
		t.Fatal(err)
	}
	mu.Lock()
	defer mu.Unlock()
	if len(bodies) != 3 || !bytes.Equal(bodies[0], bodies[1]) {
		t.Fatal("retry changed or reordered envelope")
	}
	var got domain.Event
	json.Unmarshal(bodies[0], &got)
	if got.Payload["callId"] != "call" || got.EventID != "fixed" || got.SessionID != "session" || got.Payload["aiSessionId"] != "ai" {
		t.Fatal(got)
	}
	if err := p.Publish(context.Background(), event); err == nil {
		t.Fatal("publish after close")
	}
}
func TestPublisherPermanentErrorNoRetry(t *testing.T) {
	count := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { count++; w.WriteHeader(400) }))
	defer srv.Close()
	p := NewHTTPPublisher(srv.URL, slog.Default())
	p.Publish(context.Background(), domain.Event{})
	p.Close(context.Background())
	if count != 1 {
		t.Fatal(count)
	}
}
func TestPublisherQueueBound(t *testing.T) {
	p := &HTTPPublisher{queue: make(chan []byte, 1)}
	if err := p.Publish(context.Background(), domain.Event{}); err != nil {
		t.Fatal(err)
	}
	if err := p.Publish(context.Background(), domain.Event{}); err == nil {
		t.Fatal("unbounded queue")
	}
}
