package ports

import (
	"context"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

// StartCallRequest is the Asterisk-facing start request.
type StartCallRequest struct {
	CallID      string
	SessionID   string
	AISessionID string
	SIPAddress  string
}

// CallResources are Asterisk resource IDs created for a call.
type CallResources struct {
	ChannelID       string
	BridgeID        string
	ExternalMediaID string
}

// Asterisk controls telephony via ARI.
type Asterisk interface {
	Ready(ctx context.Context) error
	// On error, nonempty resources must be retained and passed to DestroyCall for retry.
	StartCall(ctx context.Context, req StartCallRequest) (CallResources, error)
	Hangup(ctx context.Context, channelID string) error
	DestroyCall(ctx context.Context, res CallResources) error
	Subscribe(ctx context.Context, handler EventHandler) error
}

// EventHandler receives ARI channel lifecycle events.
type EventHandler func(evt ARIEvent)

// ARIEvent is a normalized Asterisk event.
type ARIEvent struct {
	Payload   map[string]any
	CallID    string
	Type      string
	ChannelID string
	State     string
	Args      []string
}

// CoreEventPublisher publishes media events toward Core.
type CoreEventPublisher interface {
	Publish(ctx context.Context, event domain.Event) error
}

// EchoSession is a per-call RTP echo loop.
type EchoSession interface {
	Start(ctx context.Context) error
	Stop(ctx context.Context) error
	Stats() RTPStats
}

// RTPStats are packet counters without audio payloads.
type RTPStats struct {
	ReceivedPackets uint64
	SentPackets     uint64
	LostPackets     uint64
	SequenceGaps    uint64
	BytesReceived   uint64
	BytesSent       uint64
}

// EchoFactory creates echo sessions bound to a UDP listen port.
type EchoFactory interface {
	Create(listenHost string, listenPort int) (EchoSession, int, error)
}

// VoiceSession is activated only once the SIP channel has answered.
type VoiceSession interface {
	Activate(StartCallRequest, func(ARIEvent)) error
	Control(string) error
}
type CallController interface {
	Control(context.Context, string, string) error
}
