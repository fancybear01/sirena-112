package ai

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestBoundedQueueDoesNotBlockProducer(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	c := &Client{ctx: ctx, queue: make(chan message, 1), failures: make(chan error, 1)}
	if err := c.SendPCM(make([]byte, 640)); err != nil {
		t.Fatal(err)
	}
	if err := c.SendPCM(make([]byte, 640)); !errors.Is(err, ErrBackpressure) {
		t.Fatal(err)
	}
	select {
	case <-c.failures:
	default:
		t.Fatal("overflow not reported")
	}
	if err := c.SendPCM(make([]byte, 639)); err == nil {
		t.Fatal("odd/short frame accepted")
	}
}
func TestHandshakeTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { <-r.Context().Done() }))
	defer srv.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	_, err := Dial(ctx, Config{BaseURL: "ws" + strings.TrimPrefix(srv.URL, "http")}, "s", "ai", nil, nil, nil)
	if err == nil {
		t.Fatal("handshake ignored cancellation")
	}
}
