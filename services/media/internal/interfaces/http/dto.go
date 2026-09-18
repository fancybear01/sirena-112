package httpapi

// StartCallRequest is the HTTP DTO for call.start.
type StartCallRequest struct {
	SessionID   string `json:"sessionId"`
	AISessionID string `json:"aiSessionId"`
	SIPAddress  string `json:"sipAddress"`
}

// HangupCallRequest is the HTTP DTO for call.hangup.
type HangupCallRequest struct {
	CallID    string `json:"callId"`
	SessionID string `json:"sessionId"`
}

// CallResponse is returned for start/get/hangup.
type CallResponse struct {
	CallID      string `json:"callId"`
	SessionID   string `json:"sessionId"`
	AISessionID string `json:"aiSessionId,omitempty"`
	SIPAddress  string `json:"sipAddress,omitempty"`
	State       string `json:"state"`
	ChannelID   string `json:"channelId,omitempty"`
	BridgeID    string `json:"bridgeId,omitempty"`
}

// ErrorResponse is a machine-readable error body.
type ErrorResponse struct {
	Error   string `json:"error"`
	Message string `json:"message"`
}
