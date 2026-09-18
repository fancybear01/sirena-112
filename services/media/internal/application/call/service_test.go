package call_test

import (
	"context"
	"log/slog"
	"os"
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
func (f *fakeAsterisk) DestroyCall(ctx context.Context, res ports.CallResources) error { return nil }
func (f *fakeAsterisk) Subscribe(ctx context.Context, handler ports.EventHandler) error {
	return nil
}

type fakeCore struct {
	events []domain.Event
}

func (f *fakeCore) Publish(ctx context.Context, event domain.Event) error {
	f.events = append(f.events, event)
	return nil
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
