package httpapi

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"strings"

	"github.com/fancybear01/sirena-112/services/media/internal/application/call"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
	"github.com/google/uuid"
)

// Handler exposes Media internal HTTP API.
type Handler struct {
	calls    *call.Service
	asterisk ports.Asterisk
	log      *slog.Logger
}

func NewHandler(calls *call.Service, asterisk ports.Asterisk, log *slog.Logger) *Handler {
	return &Handler{calls: calls, asterisk: asterisk, log: log}
}

func (h *Handler) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", h.health)
	mux.HandleFunc("GET /ready", h.ready)
	mux.HandleFunc("POST /internal/v1/calls/start", h.startCall)
	mux.HandleFunc("POST /internal/v1/calls/hangup", h.hangupCall)
	mux.HandleFunc("GET /internal/v1/calls/{callId}", h.getCall)
	mux.HandleFunc("POST /internal/v1/speech/play", h.speechStub)
	mux.HandleFunc("POST /internal/v1/speech/cancel", h.speechStub)
	return withRequestID(mux)
}

func (h *Handler) health(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) ready(w http.ResponseWriter, r *http.Request) {
	if err := h.asterisk.Ready(r.Context()); err != nil {
		writeJSON(w, http.StatusServiceUnavailable, map[string]string{
			"status": "not_ready",
			"reason": "ari_unavailable",
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
}

func (h *Handler) startCall(w http.ResponseWriter, r *http.Request) {
	var req StartCallRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	req.SessionID = strings.TrimSpace(req.SessionID)
	req.AISessionID = strings.TrimSpace(req.AISessionID)
	req.SIPAddress = strings.TrimSpace(req.SIPAddress)

	c, err := h.calls.Start(r.Context(), call.StartCommand{
		SessionID:   req.SessionID,
		AISessionID: req.AISessionID,
		SIPAddress:  req.SIPAddress,
		RequestID:   requestID(r),
	})
	if err != nil {
		h.mapError(w, err)
		return
	}
	writeJSON(w, http.StatusAccepted, CallResponse{
		CallID:      c.ID,
		SessionID:   c.SessionID,
		AISessionID: c.AISessionID,
		SIPAddress:  c.SIPAddress,
		State:       string(c.State),
		ChannelID:   c.AsteriskChannelID,
		BridgeID:    c.BridgeID,
	})
}

func (h *Handler) hangupCall(w http.ResponseWriter, r *http.Request) {
	var req HangupCallRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeErr(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	c, err := h.calls.Hangup(r.Context(), call.HangupCommand{
		CallID:    strings.TrimSpace(req.CallID),
		SessionID: strings.TrimSpace(req.SessionID),
		RequestID: requestID(r),
	})
	if err != nil {
		h.mapError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, CallResponse{
		CallID:    c.ID,
		SessionID: c.SessionID,
		State:     string(c.State),
	})
}

func (h *Handler) getCall(w http.ResponseWriter, r *http.Request) {
	callID := r.PathValue("callId")
	c, err := h.calls.Get(callID)
	if err != nil {
		h.mapError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, CallResponse{
		CallID:      c.ID,
		SessionID:   c.SessionID,
		AISessionID: c.AISessionID,
		SIPAddress:  c.SIPAddress,
		State:       string(c.State),
		ChannelID:   c.AsteriskChannelID,
		BridgeID:    c.BridgeID,
	})
}

func (h *Handler) speechStub(w http.ResponseWriter, r *http.Request) {
	writeErr(w, http.StatusNotImplemented, "not_implemented", "speech.play/cancel are stubs until AI stream is wired")
}

func (h *Handler) mapError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, domain.ErrInvalidArgument):
		writeErr(w, http.StatusBadRequest, "invalid_argument", err.Error())
	case errors.Is(err, domain.ErrCallNotFound):
		writeErr(w, http.StatusNotFound, "not_found", err.Error())
	case errors.Is(err, domain.ErrCallExists):
		writeErr(w, http.StatusConflict, "conflict", err.Error())
	case errors.Is(err, domain.ErrARIUnavailable):
		writeErr(w, http.StatusServiceUnavailable, "ari_unavailable", err.Error())
	default:
		h.log.Error("request failed", "err", err)
		writeErr(w, http.StatusInternalServerError, "internal_error", "internal error")
	}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func writeErr(w http.ResponseWriter, status int, code, msg string) {
	writeJSON(w, status, ErrorResponse{Error: code, Message: msg})
}

func requestID(r *http.Request) string {
	if v := r.Header.Get("X-Request-Id"); v != "" {
		return v
	}
	return r.Header.Get("X-Request-ID")
}

func withRequestID(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id := requestID(r)
		if id == "" {
			id = uuid.NewString()
			r.Header.Set("X-Request-Id", id)
		}
		w.Header().Set("X-Request-Id", id)
		next.ServeHTTP(w, r)
	})
}
