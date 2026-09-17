package domain

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

type CallState string

const (
	CallStateNew      CallState = "new"
	CallStateActive   CallState = "active"
	CallStateFinished CallState = "finished"
)
