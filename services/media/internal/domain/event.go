package domain

import "time"

// Event is the Core-facing session event envelope (contracts/events.md).
type Event struct {
	EventID   string         `json:"eventId"`
	SessionID string         `json:"sessionId"`
	Type      string         `json:"type"`
	Timestamp time.Time      `json:"timestamp"`
	Source    string         `json:"source"`
	Payload   map[string]any `json:"payload"`
}

const (
	EventCallRinging  = "call.ringing"
	EventCallAnswered = "call.answered"
	EventCallEnded    = "call.ended"
	EventMediaError   = "media.error"
	EventMediaLatency = "media.latency"
	EventSystemError  = "system.error"

	EventSourceMedia = "media"
)
