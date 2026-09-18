package domain

import "fmt"

// Call is the technical media call (not a Core training session).
type Call struct {
	ID                string
	SessionID         string
	AISessionID       string
	SIPAddress        string
	State             CallState
	AsteriskChannelID string
	BridgeID          string
	ExternalMediaID   string
}

// CallState is the technical lifecycle of a media call.
type CallState string

const (
	CallStateNew      CallState = "NEW"
	CallStateRinging  CallState = "RINGING"
	CallStateActive   CallState = "ACTIVE"
	CallStateEnding   CallState = "ENDING"
	CallStateEnded    CallState = "ENDED"
	CallStateFailed   CallState = "FAILED"
)

// CanTransition reports whether moving from current to next is allowed.
func (s CallState) CanTransition(next CallState) bool {
	switch s {
	case CallStateNew:
		return next == CallStateRinging || next == CallStateFailed || next == CallStateEnding
	case CallStateRinging:
		return next == CallStateActive || next == CallStateEnding || next == CallStateFailed || next == CallStateEnded
	case CallStateActive:
		return next == CallStateEnding || next == CallStateEnded || next == CallStateFailed
	case CallStateEnding:
		return next == CallStateEnded || next == CallStateFailed
	case CallStateEnded, CallStateFailed:
		return false
	default:
		return false
	}
}

// Transition applies a state change or returns an error.
func (c *Call) Transition(next CallState) error {
	if !c.State.CanTransition(next) {
		return fmt.Errorf("%w: %s -> %s", ErrInvalidTransition, c.State, next)
	}
	c.State = next
	return nil
}

// IsTerminal reports whether the call is finished.
func (s CallState) IsTerminal() bool {
	return s == CallStateEnded || s == CallStateFailed
}
