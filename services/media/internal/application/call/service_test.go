package call_test

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/application/call"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

type fakeAsterisk struct {
	started int
	hangups int
}

func (f *fakeAsterisk) Ready(ctx context.Context) error { return nil }
func (f *fakeAsterisk) StartCall(ctx context.Context, req ports.StartCallRequest) (ports.CallResources, error) {
	f.started++
	return ports.CallResources{ChannelID: "ch-1", BridgeID: "br-1", ExternalMediaID: "ext-1"}, nil
}
func (f *fakeAsterisk) Hangup(ctx context.Context, channelID string) error {
	f.hangups++
	return nil
}
func (f *fakeAsterisk) DestroyCall(ctx context.Context, res ports.CallResources) error {
	f.hangups++
	return nil
}
func (f *fakeAsterisk) Subscribe(ctx context.Context, handler ports.EventHandler) error {
	return nil
}

type fakeCore struct {
	events []domain.Event
}

type recordingAsterisk struct {
	fakeAsterisk
	last ports.StartCallRequest
	fail bool
}

func (a *recordingAsterisk) StartCall(ctx context.Context, req ports.StartCallRequest) (ports.CallResources, error) {
	a.last = req
	return a.fakeAsterisk.StartCall(ctx, req)
}
func (a *recordingAsterisk) TakeRecording(callID string) (*ports.RecordingInfo, error) {
	if a.fail {
		return nil, errors.New("disk unavailable")
	}
	return &ports.RecordingInfo{SessionID: a.last.SessionID, CallID: callID, DurationMS: 120, Bytes: 1964}, nil
}

func TestRecordingAfterTranscriptBeforeEndedAndStorageFailure(t *testing.T) {
	a := &recordingAsterisk{}
	core := &fakeCore{}
	svc := call.NewService(a, core, slog.Default())
	for i := 0; i < 2; i++ {
		a.fail = i == 1
		c, err := svc.Start(context.Background(), call.StartCommand{SessionID: "session", AISessionID: "ai", SIPAddress: "1001"})
		if err != nil {
			t.Fatal(err)
		}
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "ChannelStateChange", State: "Up"})
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "transcript.final", Payload: map[string]any{"text": "hello", "sequence": 1}})
		if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID}); err != nil {
			t.Fatal(err)
		}
		var order []string
		for _, e := range core.events {
			if e.Payload["callId"] == c.ID {
				order = append(order, e.Type)
			}
		}
		if i == 0 {
			if len(order) < 5 || order[len(order)-3] != "transcript.final" || order[len(order)-2] != "recording.ready" || order[len(order)-1] != "call.ended" {
				t.Fatalf("wrong order: %v", order)
			}
		} else {
			if len(order) < 5 || order[len(order)-2] != "media.error" || order[len(order)-1] != "call.ended" {
				t.Fatalf("storage failure: %v", order)
			}
		}
	}
}

func (f *fakeCore) Publish(ctx context.Context, event domain.Event) error {
	f.events = append(f.events, event)
	return nil
}

func TestCapacityRejectsBeforeARIAndReleasesAfterHangup(t *testing.T) {
	ast := &fakeAsterisk{}
	svc := call.NewService(ast, &fakeCore{}, slog.Default())
	svc.SetMaxCalls(1)
	first, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s1", AISessionID: "ai1", SIPAddress: "PJSIP/smoke-out"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s2", AISessionID: "ai2", SIPAddress: "PJSIP/smoke-out"}); !errors.Is(err, domain.ErrCapacityExhausted) {
		t.Fatalf("expected explicit capacity error, got %v", err)
	}
	if ast.started != 1 {
		t.Fatalf("overloaded call reached ARI: %d starts", ast.started)
	}
	if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: first.ID}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s2", AISessionID: "ai2", SIPAddress: "PJSIP/smoke-out"}); err != nil {
		t.Fatalf("slot not reusable: %v", err)
	}
}

func TestStartHangupPublishesEvents(t *testing.T) {
	ast := &fakeAsterisk{}
	core := &fakeCore{}
	svc := call.NewService(ast, core, slog.New(slog.NewTextHandler(os.Stderr, nil)))

	c, err := svc.Start(context.Background(), call.StartCommand{
		SessionID:   "sess-1",
		AISessionID: "ai-1",
		SIPAddress:  "PJSIP/1001",
	})
	if err != nil {
		t.Fatal(err)
	}
	if c.State != domain.CallStateRinging {
		t.Fatalf("state %s", c.State)
	}
	svc.HandleARIEvent(ports.ARIEvent{Type: "ChannelStateChange", ChannelID: "ch-1", State: "Up"})
	got, _ := svc.Get(c.ID)
	if got.State != domain.CallStateActive {
		t.Fatalf("expected ACTIVE, got %s", got.State)
	}
	_, err = svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID})
	if err != nil {
		t.Fatal(err)
	}
	if ast.hangups == 0 {
		t.Fatal("expected hangup")
	}
	// idempotent
	_, err = svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID})
	if err != nil {
		t.Fatal(err)
	}
}

// callbackAsterisk can deliver events before StartCall returns, as real ARI does.
type callbackAsterisk struct {
	fakeAsterisk
	start   func(ports.StartCallRequest) (ports.CallResources, error)
	destroy func(context.Context, ports.CallResources) error
}

func (f *callbackAsterisk) StartCall(ctx context.Context, req ports.StartCallRequest) (ports.CallResources, error) {
	return f.start(req)
}
func (f *callbackAsterisk) DestroyCall(ctx context.Context, res ports.CallResources) error {
	if f.destroy != nil {
		return f.destroy(ctx, res)
	}
	return nil
}

func TestEarlyEventsAndConcurrentHangup(t *testing.T) {
	ast := &callbackAsterisk{}
	core := &fakeCore{}
	svc := call.NewService(ast, core, slog.Default())
	var cleanups atomic.Int32
	ast.destroy = func(ctx context.Context, _ ports.CallResources) error { cleanups.Add(1); return ctx.Err() }
	ast.start = func(req ports.StartCallRequest) (ports.CallResources, error) {
		svc.HandleARIEvent(ports.ARIEvent{CallID: req.CallID, ChannelID: "early", Type: "ChannelStateChange", State: "Up"})
		return ports.CallResources{ChannelID: "early"}, nil
	}
	c, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"})
	if err != nil || c.State != domain.CallStateActive {
		t.Fatalf("early answer lost: %+v %v", c, err)
	}
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = svc.Get(c.ID)
			_, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID})
			if err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if cleanups.Load() != 1 {
		t.Fatalf("cleanups=%d", cleanups.Load())
	}
	if c.State != domain.CallStateActive {
		t.Fatal("returned snapshot mutated")
	}
	want := []string{domain.EventCallRinging, domain.EventCallAnswered, domain.EventCallEnded}
	if len(core.events) != len(want) {
		t.Fatalf("events=%+v", core.events)
	}
	for i, typ := range want {
		if core.events[i].Type != typ {
			t.Fatalf("events=%+v", core.events)
		}
	}
}

func TestConcurrentStartReservesSession(t *testing.T) {
	entered, release := make(chan struct{}), make(chan struct{})
	ast := &callbackAsterisk{start: func(req ports.StartCallRequest) (ports.CallResources, error) {
		close(entered)
		<-release
		return ports.CallResources{ChannelID: req.CallID}, nil
	}}
	svc := call.NewService(ast, &fakeCore{}, slog.Default())
	cmd := call.StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"}
	done := make(chan error, 1)
	go func() { _, err := svc.Start(context.Background(), cmd); done <- err }()
	<-entered
	_, err := svc.Start(context.Background(), cmd)
	close(release)
	if !errors.Is(err, domain.ErrCallExists) {
		t.Fatalf("expected conflict: %v", err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	svc.Shutdown(context.Background())
	if _, err := svc.Start(context.Background(), cmd); !errors.Is(err, domain.ErrARIUnavailable) {
		t.Fatalf("start after shutdown: %v", err)
	}
}

func TestFailedStartCanRetryAndEarlyHangupCleansUp(t *testing.T) {
	ast := &callbackAsterisk{}
	svc := call.NewService(ast, &fakeCore{}, slog.Default())
	cmd := call.StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"}
	ast.start = func(ports.StartCallRequest) (ports.CallResources, error) {
		return ports.CallResources{}, errors.New("dial failed")
	}
	if _, err := svc.Start(context.Background(), cmd); err == nil {
		t.Fatal("expected failure")
	}
	cleaned := false
	ast.destroy = func(context.Context, ports.CallResources) error { cleaned = true; return nil }
	ast.start = func(req ports.StartCallRequest) (ports.CallResources, error) {
		svc.HandleARIEvent(ports.ARIEvent{CallID: req.CallID, Type: "ChannelDestroyed"})
		return ports.CallResources{ChannelID: req.CallID}, nil
	}
	c, err := svc.Start(context.Background(), cmd)
	if err != nil || c.State != domain.CallStateEnded || !cleaned {
		t.Fatalf("early hangup: %+v %v cleaned=%v", c, err, cleaned)
	}
}

func TestCleanupFailureIsReportedAndRetryable(t *testing.T) {
	ast := &callbackAsterisk{start: func(req ports.StartCallRequest) (ports.CallResources, error) {
		return ports.CallResources{ChannelID: req.CallID}, nil
	}}
	svc := call.NewService(ast, &fakeCore{}, slog.Default())
	c, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"})
	if err != nil {
		t.Fatal(err)
	}
	ast.destroy = func(ctx context.Context, _ ports.CallResources) error {
		if ctx.Err() != nil {
			t.Fatal("cancelled cleanup")
		}
		return errors.New("ARI down")
	}
	if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID}); err == nil {
		t.Fatal("cleanup failure swallowed")
	}
	if _, err := svc.Get(c.ID); err != nil {
		t.Fatal("lost IDs needed for retry")
	}
	ast.destroy = func(context.Context, ports.CallResources) error { return nil }
	if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.Get(c.ID); !errors.Is(err, domain.ErrCallNotFound) {
		t.Fatalf("not removed: %v", err)
	}
	if _, err := svc.Hangup(context.Background(), call.HangupCommand{}); !errors.Is(err, domain.ErrInvalidArgument) {
		t.Fatalf("empty hangup: %v", err)
	}
}

func TestAIErrorCorrelationsAndNextCall(t *testing.T) {
	ast := &fakeAsterisk{}
	core := &fakeCore{}
	svc := call.NewService(ast, core, slog.Default())
	for i := 0; i < 2; i++ {
		c, err := svc.Start(context.Background(), call.StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"})
		if err != nil {
			t.Fatal(err)
		}
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "ChannelStateChange", State: "Up"})
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "transcript.final", Payload: map[string]any{"text": "test", "simulated": true}})
		if i == 0 {
			svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "media.error", Payload: map[string]any{"message": "AI disconnected"}})
		} else {
			if _, err := svc.Hangup(context.Background(), call.HangupCommand{CallID: c.ID}); err != nil {
				t.Fatal(err)
			}
		}
		before := len(core.events)
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "ChannelStateChange", State: "Up"})
		svc.HandleARIEvent(ports.ARIEvent{CallID: c.ID, Type: "media.error"})
		if len(core.events) != before {
			t.Fatal("late events resurrected terminal call")
		}
	}
	for _, evt := range core.events {
		if evt.EventID == "" || evt.SessionID != "s" || evt.Payload["callId"] == nil || evt.Payload["aiSessionId"] != "ai" {
			t.Fatalf("lost correlation: %+v", evt)
		}
	}
	if ast.hangups != 2 {
		t.Fatal("cleanup not called for disconnect/hangup")
	}
}
