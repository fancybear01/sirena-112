package ari

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"strings"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type factoryFunc func(string, int) (ports.EchoSession, int, error)

func (f factoryFunc) Create(host string, port int) (ports.EchoSession, int, error) {
	return f(host, port)
}
func response(code int) *http.Response {
	return &http.Response{StatusCode: code, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(`{"id":"test"}`))}
}
func unitClient(transport roundTripFunc) *Client {
	c := NewClient(Config{RTPPort: 18000, RTPPortEnd: 18001, BaseURL: "http://ari.test/ari", Log: slog.Default(),
		EchoFactory: factoryFunc(func(_ string, port int) (ports.EchoSession, int, error) { return &trackedEcho{}, port, nil })})
	c.http = &http.Client{Transport: transport}
	c.connected.Store(true)
	return c
}
func receiveEvent(t *testing.T, events <-chan ports.ARIEvent) ports.ARIEvent {
	t.Helper()
	select {
	case evt := <-events:
		return evt
	case <-time.After(time.Second):
		t.Fatal("event blocked")
		return ports.ARIEvent{}
	}
}

func TestSlowSetupDoesNotBlockOtherCallEvents(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	c := unitClient(func(r *http.Request) (*http.Response, error) {
		if r.URL.Path == "/ari/bridges" && r.URL.Query().Get("bridgeId") == "slow-bridge" {
			close(entered)
			<-release
		}
		return response(200), nil
	})
	events := make(chan ports.ARIEvent, 4)
	c.handler = func(evt ports.ARIEvent) { events <- evt }
	fast, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "fast", SIPAddress: "1001"})
	if err != nil {
		t.Fatal(err)
	}
	defer c.DestroyCall(context.Background(), fast)
	done := make(chan error, 1)
	go func() {
		res, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "slow", SIPAddress: "1002"})
		if err == nil {
			err = c.DestroyCall(context.Background(), res)
		}
		done <- err
	}()
	<-entered
	defer close(release)
	// The WebSocket reader returns immediately even for the initializing call.
	c.handleWSMessage(context.Background(), []byte(`{"type":"StasisStart","channel":{"id":"slow"}}`))
	c.handleWSMessage(context.Background(), []byte(`{"type":"StasisStart","channel":{"id":"fast"}}`))
	if evt := receiveEvent(t, events); evt.CallID != "fast" || evt.State != "Up" {
		t.Fatalf("event=%+v", evt)
	}
	// Check completion after releasing setup, without relying on sleeps.
	t.Cleanup(func() {
		select {
		case err := <-done:
			if err != nil {
				t.Error(err)
			}
		case <-time.After(time.Second):
			t.Error("slow setup stuck")
		}
	})
}

func TestRollbackFailureRetainsResourcesAndPort(t *testing.T) {
	var unavailable atomic.Bool
	unavailable.Store(true)
	c := unitClient(func(r *http.Request) (*http.Response, error) {
		if unavailable.Load() {
			return response(503), nil
		}
		return response(200), nil
	})
	c.rtpPortEnd = c.rtpPort // one slot
	res, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "failed", SIPAddress: "1001"})
	if err == nil || res.ChannelID == "" {
		t.Fatalf("rollback IDs lost: %+v %v", res, err)
	}
	if _, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "next", SIPAddress: "1002"}); !errors.Is(err, domain.ErrCapacityExhausted) {
		t.Fatalf("reserved port reused: %v", err)
	}
	unavailable.Store(false)
	if err := c.DestroyCall(context.Background(), res); err != nil {
		t.Fatal(err)
	}
	next, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "next", SIPAddress: "1002"})
	if err != nil {
		t.Fatalf("port not released: %v", err)
	}
	if err := c.DestroyCall(context.Background(), next); err != nil {
		t.Fatal(err)
	}
}

func TestPortPoolSkipsOccupiedPorts(t *testing.T) {
	c := unitClient(func(*http.Request) (*http.Response, error) { return response(200), nil })
	c.echoFactory = factoryFunc(func(_ string, port int) (ports.EchoSession, int, error) {
		if port == 18000 {
			return nil, 0, syscall.EADDRINUSE
		}
		return &trackedEcho{}, port, nil
	})
	res, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "call", SIPAddress: "1001"})
	if err != nil {
		t.Fatal(err)
	}
	if c.runtimes["call"].port != 18001 {
		t.Fatal("did not skip occupied port")
	}
	if _, err := c.StartCall(context.Background(), ports.StartCallRequest{CallID: "other", SIPAddress: "1002"}); !errors.Is(err, domain.ErrCapacityExhausted) {
		t.Fatalf("capacity error=%v", err)
	}
	if err := c.DestroyCall(context.Background(), res); err != nil {
		t.Fatal(err)
	}
}

func TestBoundedQueueOverflowFailsCall(t *testing.T) {
	c := unitClient(func(*http.Request) (*http.Response, error) { return response(200), nil })
	rt := &callRuntime{callID: "call", channelID: "ch", ready: make(chan struct{}), done: make(chan struct{}), overflow: make(chan struct{}), events: make(chan ports.ARIEvent, 1)}
	c.runtimes["call"] = rt
	c.byChan["ch"] = "call"
	events := make(chan ports.ARIEvent, 2)
	c.handler = func(evt ports.ARIEvent) { events <- evt }
	c.enqueue(ports.ARIEvent{ChannelID: "ch", Type: "ignored"})
	c.enqueue(ports.ARIEvent{ChannelID: "ch", Type: "ignored"})
	close(rt.ready)
	done := make(chan struct{})
	go func() { c.runEvents(rt); close(done) }()
	for {
		evt := receiveEvent(t, events)
		if evt.State == "Failed" {
			break
		}
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("overflow worker did not exit")
	}
}
