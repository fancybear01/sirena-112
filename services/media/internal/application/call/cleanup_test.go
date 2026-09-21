package call

import (
	"context"
	"errors"
	"log/slog"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

type rollbackAsterisk struct {
	cleanupErr error
	destroyed  int
}

func (*rollbackAsterisk) Ready(context.Context) error                         { return nil }
func (*rollbackAsterisk) Subscribe(context.Context, ports.EventHandler) error { return nil }
func (*rollbackAsterisk) Hangup(context.Context, string) error                { return nil }
func (*rollbackAsterisk) StartCall(_ context.Context, req ports.StartCallRequest) (ports.CallResources, error) {
	return ports.CallResources{ChannelID: req.CallID, BridgeID: req.CallID + "-bridge", ExternalMediaID: req.CallID + "-media"}, errors.New("rollback pending")
}
func (a *rollbackAsterisk) DestroyCall(ctx context.Context, _ ports.CallResources) error {
	a.destroyed++
	if ctx.Err() != nil {
		return ctx.Err()
	}
	return a.cleanupErr
}

type eventsSink struct{ events []domain.Event }

func (s *eventsSink) Publish(_ context.Context, e domain.Event) error {
	s.events = append(s.events, e)
	return nil
}

func TestFailedStartCleanupRetriesAndReleasesSession(t *testing.T) {
	ast := &rollbackAsterisk{cleanupErr: errors.New("ARI down")}
	sink := &eventsSink{}
	svc := NewService(ast, sink, slog.Default())
	cmd := StartCommand{SessionID: "session", AISessionID: "ai", SIPAddress: "1001"}
	if _, err := svc.Start(context.Background(), cmd); err == nil {
		t.Fatal("expected failed start")
	}
	id := svc.bySession[cmd.SessionID]
	rt := svc.byID[id]
	if rt == nil || rt.resources.ChannelID == "" || rt.cleanupErr == nil {
		t.Fatal("failed start resources lost")
	}
	if _, err := svc.Start(context.Background(), cmd); !errors.Is(err, domain.ErrCallExists) {
		t.Fatalf("session reservation lost: %v", err)
	}
	svc.retryCleanup(context.Background())
	if ast.destroyed != 1 || svc.byID[id] == nil {
		t.Fatal("failed retry lost resources")
	}
	ast.cleanupErr = nil
	svc.retryCleanup(context.Background())
	if ast.destroyed != 2 || len(svc.byID) != 0 || len(svc.bySession) != 0 || len(svc.byChannel) != 0 {
		t.Fatal("successful retry did not release resources")
	}
	ended := 0
	for _, evt := range sink.events {
		if evt.Type == domain.EventCallEnded {
			ended++
		}
	}
	if ended != 1 {
		t.Fatalf("ended events=%d", ended)
	}
	svc.retryCleanup(context.Background())
	if ast.destroyed != 2 {
		t.Fatal("repeated cleanup after success")
	}
}

func TestCancelledRetryDoesNoWork(t *testing.T) {
	ast := &rollbackAsterisk{}
	svc := NewService(ast, &eventsSink{}, slog.Default())
	_, _ = svc.Start(context.Background(), StartCommand{SessionID: "s", AISessionID: "ai", SIPAddress: "1001"})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	svc.retryCleanup(ctx)
	if ast.destroyed != 0 {
		t.Fatal("retry ignored cancellation")
	}
	svc.Shutdown(context.Background())
}
