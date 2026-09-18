package call

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
	"github.com/google/uuid"
)

// StartCommand is the application input for starting a call.
type StartCommand struct {
	SessionID   string
	AISessionID string
	SIPAddress  string
	RequestID   string
}

// HangupCommand ends a call by callId or sessionId.
type HangupCommand struct {
	CallID    string
	SessionID string
	RequestID string
}

// Service manages technical call lifecycle.
type Service struct {
	asterisk ports.Asterisk
	core     ports.CoreEventPublisher
	log      *slog.Logger

	mu          sync.RWMutex
	byID        map[string]*runtime
	bySession   map[string]string
	byChannel   map[string]string
}

type runtime struct {
	call      *domain.Call
	resources ports.CallResources
	cancel    context.CancelFunc
	done      bool
}

func NewService(asterisk ports.Asterisk, core ports.CoreEventPublisher, log *slog.Logger) *Service {
	return &Service{
		asterisk:  asterisk,
		core:      core,
		log:       log,
		byID:      map[string]*runtime{},
		bySession: map[string]string{},
		byChannel: map[string]string{},
	}
}

// HandleARIEvent maps Asterisk events onto call state + Core events.
func (s *Service) HandleARIEvent(evt ports.ARIEvent) {
	s.mu.RLock()
	callID := s.byChannel[evt.ChannelID]
	rt := s.byID[callID]
	s.mu.RUnlock()
	if rt == nil {
		return
	}

	ctx := context.Background()
	switch evt.Type {
	case "ChannelStateChange":
		switch evt.State {
		case "Ringing", "Ring":
			s.transition(ctx, rt, domain.CallStateRinging, domain.EventCallRinging)
		case "Up":
			s.transition(ctx, rt, domain.CallStateActive, domain.EventCallAnswered)
		}
	case "ChannelDestroyed", "StasisEnd":
		if rt.call.State.IsTerminal() {
			return
		}
		s.finish(ctx, rt, domain.CallStateEnded, domain.EventCallEnded, nil)
	}
}

func (s *Service) Start(ctx context.Context, cmd StartCommand) (*domain.Call, error) {
	if cmd.SessionID == "" || cmd.AISessionID == "" || cmd.SIPAddress == "" {
		return nil, fmt.Errorf("%w: sessionId, aiSessionId and sipAddress are required", domain.ErrInvalidArgument)
	}

	s.mu.Lock()
	if existing, ok := s.bySession[cmd.SessionID]; ok {
		rt := s.byID[existing]
		s.mu.Unlock()
		if rt != nil && !rt.call.State.IsTerminal() {
			return nil, fmt.Errorf("%w: %s", domain.ErrCallExists, cmd.SessionID)
		}
	}
	s.mu.Unlock()

	callID := uuid.NewString()
	call := &domain.Call{
		ID:          callID,
		SessionID:   cmd.SessionID,
		AISessionID: cmd.AISessionID,
		SIPAddress:  cmd.SIPAddress,
		State:       domain.CallStateNew,
	}

	res, err := s.asterisk.StartCall(ctx, ports.StartCallRequest{
		CallID:      callID,
		SessionID:   cmd.SessionID,
		AISessionID: cmd.AISessionID,
		SIPAddress:  cmd.SIPAddress,
	})
	if err != nil {
		call.State = domain.CallStateFailed
		_ = s.publish(ctx, call, domain.EventMediaError, map[string]any{
			"callId": callID,
			"error":  err.Error(),
		})
		return nil, err
	}

	call.AsteriskChannelID = res.ChannelID
	call.BridgeID = res.BridgeID
	call.ExternalMediaID = res.ExternalMediaID

	_, cancel := context.WithCancel(context.Background())
	rt := &runtime{call: call, resources: res, cancel: cancel}

	s.mu.Lock()
	s.byID[callID] = rt
	s.bySession[cmd.SessionID] = callID
	s.byChannel[res.ChannelID] = callID
	s.mu.Unlock()

	s.log.Info("call created",
		"requestId", cmd.RequestID,
		"sessionId", cmd.SessionID,
		"callId", callID,
		"channelId", res.ChannelID,
	)

	// Outbound dial usually rings immediately.
	s.transition(ctx, rt, domain.CallStateRinging, domain.EventCallRinging)
	return call, nil
}

func (s *Service) Hangup(ctx context.Context, cmd HangupCommand) (*domain.Call, error) {
	rt := s.find(cmd.CallID, cmd.SessionID)
	if rt == nil {
		// Idempotent hangup: already gone.
		return &domain.Call{ID: cmd.CallID, SessionID: cmd.SessionID, State: domain.CallStateEnded}, nil
	}
	if rt.call.State.IsTerminal() {
		return rt.call, nil
	}
	_ = rt.call.Transition(domain.CallStateEnding)
	_ = s.asterisk.Hangup(ctx, rt.resources.ChannelID)
	s.finish(ctx, rt, domain.CallStateEnded, domain.EventCallEnded, nil)
	return rt.call, nil
}

func (s *Service) Get(callID string) (*domain.Call, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	rt := s.byID[callID]
	if rt == nil {
		return nil, domain.ErrCallNotFound
	}
	cp := *rt.call
	return &cp, nil
}

func (s *Service) find(callID, sessionID string) *runtime {
	s.mu.RLock()
	defer s.mu.RUnlock()
	if callID != "" {
		return s.byID[callID]
	}
	if sessionID != "" {
		return s.byID[s.bySession[sessionID]]
	}
	return nil
}

func (s *Service) transition(ctx context.Context, rt *runtime, next domain.CallState, eventType string) {
	if err := rt.call.Transition(next); err != nil {
		return
	}
	s.log.Info("call state",
		"sessionId", rt.call.SessionID,
		"callId", rt.call.ID,
		"channelId", rt.call.AsteriskChannelID,
		"state", rt.call.State,
	)
	_ = s.publish(ctx, rt.call, eventType, map[string]any{
		"callId":      rt.call.ID,
		"aiSessionId": rt.call.AISessionID,
		"channelId":   rt.call.AsteriskChannelID,
		"sipAddress":  rt.call.SIPAddress,
	})
}

func (s *Service) finish(ctx context.Context, rt *runtime, state domain.CallState, eventType string, cause error) {
	s.mu.Lock()
	if rt.done {
		s.mu.Unlock()
		return
	}
	rt.done = true
	if !rt.call.State.IsTerminal() {
		if err := rt.call.Transition(state); err != nil {
			rt.call.State = state
		}
	}
	s.mu.Unlock()

	_ = s.asterisk.DestroyCall(ctx, rt.resources)
	if rt.cancel != nil {
		rt.cancel()
	}
	payload := map[string]any{
		"callId":      rt.call.ID,
		"aiSessionId": rt.call.AISessionID,
		"channelId":   rt.call.AsteriskChannelID,
	}
	if cause != nil {
		payload["error"] = cause.Error()
	}
	_ = s.publish(ctx, rt.call, eventType, payload)

	s.mu.Lock()
	delete(s.byID, rt.call.ID)
	delete(s.bySession, rt.call.SessionID)
	delete(s.byChannel, rt.resources.ChannelID)
	s.mu.Unlock()
}

func (s *Service) publish(ctx context.Context, call *domain.Call, typ string, payload map[string]any) error {
	evt := domain.Event{
		EventID:   uuid.NewString(),
		SessionID: call.SessionID,
		Type:      typ,
		Timestamp: time.Now().UTC(),
		Source:    domain.EventSourceMedia,
		Payload:   payload,
	}
	return s.core.Publish(ctx, evt)
}
