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

	mu        sync.RWMutex
	closing   bool
	byID      map[string]*runtime
	bySession map[string]string
	byChannel map[string]string
}

type runtime struct {
	mu         sync.Mutex // serializes state changes, publication and cleanup for this call
	call       *domain.Call
	resources  ports.CallResources
	ready      chan struct{}
	starting   bool
	pending    []ports.ARIEvent
	done       bool
	cleanupErr error
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
	callID := evt.CallID
	if callID == "" {
		callID = s.byChannel[evt.ChannelID]
	}
	rt := s.byID[callID]
	s.mu.RUnlock()
	if rt == nil {
		return
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	if rt.starting {
		rt.pending = append(rt.pending, evt)
		return
	}
	s.handleEvent(rt, evt)
}

// Called with the runtime lock held.
func (s *Service) handleEvent(rt *runtime, evt ports.ARIEvent) {
	if rt.done {
		return
	}
	ctx := context.Background()
	switch evt.Type {
	case "transcript.final":
		_ = s.publish(ctx, rt.call, "transcript.final", evt.Payload)
	case "media.error":
		_ = s.publish(ctx, rt.call, domain.EventMediaError, evt.Payload)
		s.finish(ctx, rt, domain.CallStateFailed, domain.EventCallEnded, nil)
	case "ChannelStateChange":
		switch evt.State {
		case "Ring", "Ringing":
			s.transition(ctx, rt, domain.CallStateRinging, domain.EventCallRinging)
		case "Up":
			s.transition(ctx, rt, domain.CallStateActive, domain.EventCallAnswered)
		}
	case "ChannelDestroyed", "StasisEnd":
		if evt.State == "Failed" {
			_ = s.publish(ctx, rt.call, domain.EventMediaError, map[string]any{"message": "media channel failed"})
			s.finish(ctx, rt, domain.CallStateFailed, domain.EventCallEnded, fmt.Errorf("media channel failed"))
		} else {
			s.finish(ctx, rt, domain.CallStateEnded, domain.EventCallEnded, nil)
		}
	}
}

func (s *Service) Start(ctx context.Context, cmd StartCommand) (*domain.Call, error) {
	if cmd.SessionID == "" || cmd.AISessionID == "" || cmd.SIPAddress == "" {
		return nil, fmt.Errorf("%w: sessionId, aiSessionId and sipAddress are required", domain.ErrInvalidArgument)
	}

	callID := uuid.NewString()
	call := &domain.Call{
		ID:          callID,
		SessionID:   cmd.SessionID,
		AISessionID: cmd.AISessionID,
		SIPAddress:  cmd.SIPAddress,
		State:       domain.CallStateNew,
	}

	rt := &runtime{call: call, ready: make(chan struct{}), starting: true}
	s.mu.Lock()
	if s.closing {
		s.mu.Unlock()
		return nil, domain.ErrARIUnavailable
	}
	if _, exists := s.bySession[cmd.SessionID]; exists {
		s.mu.Unlock()
		return nil, fmt.Errorf("%w: %s", domain.ErrCallExists, cmd.SessionID)
	}
	s.byID[callID] = rt
	s.bySession[cmd.SessionID] = callID
	s.mu.Unlock()

	res, err := s.asterisk.StartCall(ctx, ports.StartCallRequest{
		CallID:      callID,
		SessionID:   cmd.SessionID,
		AISessionID: cmd.AISessionID,
		SIPAddress:  cmd.SIPAddress,
	})
	rt.mu.Lock()
	defer rt.mu.Unlock()
	defer close(rt.ready)
	rt.starting = false
	rt.resources = res
	call.AsteriskChannelID = res.ChannelID
	call.BridgeID = res.BridgeID
	call.ExternalMediaID = res.ExternalMediaID
	s.mu.Lock()
	if res.ChannelID != "" {
		s.byChannel[res.ChannelID] = callID
	}
	s.mu.Unlock()
	if err != nil {
		call.State = domain.CallStateFailed
		rt.done = true
		rt.pending = nil
		_ = s.publish(context.Background(), call, domain.EventMediaError, map[string]any{"callId": callID, "error": err.Error()})
		if res != (ports.CallResources{}) {
			rt.cleanupErr = err
		} else {
			s.remove(rt)
		}
		return nil, err
	}
	s.transition(context.Background(), rt, domain.CallStateRinging, domain.EventCallRinging)
	for _, evt := range rt.pending {
		s.handleEvent(rt, evt)
	}
	rt.pending = nil
	cp := *call
	return &cp, nil
}

func (s *Service) Hangup(ctx context.Context, cmd HangupCommand) (*domain.Call, error) {
	if cmd.CallID == "" && cmd.SessionID == "" {
		return nil, fmt.Errorf("%w: callId or sessionId is required", domain.ErrInvalidArgument)
	}
	rt := s.find(cmd.CallID, cmd.SessionID)
	if rt == nil {
		return &domain.Call{ID: cmd.CallID, SessionID: cmd.SessionID, State: domain.CallStateEnded}, nil
	}
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	case <-rt.ready:
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	if cmd.SessionID != "" && cmd.SessionID != rt.call.SessionID {
		return nil, fmt.Errorf("%w: callId and sessionId do not match", domain.ErrInvalidArgument)
	}
	if !rt.done || rt.cleanupErr != nil {
		_ = rt.call.Transition(domain.CallStateEnding)
		if err := s.finish(ctx, rt, domain.CallStateEnded, domain.EventCallEnded, nil); err != nil {
			return nil, err
		}
	}
	cp := *rt.call
	return &cp, nil
}

func (s *Service) Get(callID string) (*domain.Call, error) {
	rt := s.find(callID, "")
	if rt == nil {
		return nil, domain.ErrCallNotFound
	}
	rt.mu.Lock()
	defer rt.mu.Unlock()
	cp := *rt.call
	return &cp, nil
}

// Shutdown rejects new calls and releases active calls after HTTP has drained.
func (s *Service) Shutdown(ctx context.Context) {
	s.mu.Lock()
	s.closing = true
	ids := make([]string, 0, len(s.byID))
	for id := range s.byID {
		ids = append(ids, id)
	}
	s.mu.Unlock()
	var wg sync.WaitGroup
	for _, id := range ids {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.Hangup(ctx, HangupCommand{CallID: id}); err != nil {
				s.log.Error("shutdown call failed", "callId", id, "err", err)
			}
		}()
	}
	wg.Wait()
}

// RunCleanup retries failed cleanup for both failed starts and terminated calls.
// It owns no persistent state: resources are retained in the in-memory registry.
func (s *Service) RunCleanup(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			s.retryCleanup(ctx)
		}
	}
}

func (s *Service) retryCleanup(ctx context.Context) {
	s.mu.RLock()
	calls := make([]*runtime, 0, len(s.byID))
	for _, rt := range s.byID {
		calls = append(calls, rt)
	}
	s.mu.RUnlock()
	for _, rt := range calls {
		if ctx.Err() != nil {
			return
		}
		if !rt.mu.TryLock() {
			continue
		}
		if rt.cleanupErr != nil {
			_ = s.finish(ctx, rt, domain.CallStateFailed, domain.EventCallEnded, nil)
		}
		rt.mu.Unlock()
	}
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

func (s *Service) finish(ctx context.Context, rt *runtime, state domain.CallState, eventType string, cause error) error {
	if rt.done && rt.cleanupErr == nil {
		return nil
	}
	rt.done = true
	// Request cancellation must not prevent resource cleanup.
	cleanupCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	rt.cleanupErr = s.asterisk.DestroyCall(cleanupCtx, rt.resources)
	if rt.cleanupErr != nil {
		rt.call.State = domain.CallStateFailed
		s.log.Error("call cleanup failed", "callId", rt.call.ID, "err", rt.cleanupErr)
		_ = s.publish(cleanupCtx, rt.call, domain.EventMediaError, map[string]any{"callId": rt.call.ID, "error": rt.cleanupErr.Error()})
		// Keep IDs and the session reservation so a repeated hangup can retry cleanup.
		return rt.cleanupErr
	}
	if source, ok := s.asterisk.(ports.RecordingSource); ok {
		record, recordErr := source.TakeRecording(rt.call.ID)
		if recordErr != nil {
			state = domain.CallStateFailed
			_ = s.publish(cleanupCtx, rt.call, domain.EventMediaError, map[string]any{"message": "call recording failed"})
			s.log.Error("call recording failed", "callId", rt.call.ID, "err", recordErr)
		} else if record != nil {
			if err := s.publish(cleanupCtx, rt.call, "recording.ready", map[string]any{
				"recordingId": record.CallID, "durationMs": record.DurationMS,
				"bytes": record.Bytes, "format": "wav", "sampleRate": 8000, "channels": 2,
				"url": "/api/teacher/sessions/" + record.SessionID + "/recording",
			}); err != nil {
				state = domain.CallStateFailed
				_ = s.publish(cleanupCtx, rt.call, domain.EventMediaError, map[string]any{"message": "recording metadata delivery failed"})
			}
		}
	}
	rt.call.State = state
	payload := map[string]any{"callId": rt.call.ID, "aiSessionId": rt.call.AISessionID, "channelId": rt.call.AsteriskChannelID}
	if cause != nil {
		payload["error"] = cause.Error()
	}
	_ = s.publish(cleanupCtx, rt.call, eventType, payload)
	s.remove(rt)
	return nil
}

func (s *Service) remove(rt *runtime) {
	s.mu.Lock()
	delete(s.byID, rt.call.ID)
	delete(s.bySession, rt.call.SessionID)
	delete(s.byChannel, rt.resources.ChannelID)
	s.mu.Unlock()
}

func (s *Service) publish(ctx context.Context, call *domain.Call, typ string, payload map[string]any) error {
	if payload == nil {
		payload = map[string]any{}
	}
	payload["callId"] = call.ID
	payload["aiSessionId"] = call.AISessionID
	if reason, ok := payload["error"]; ok {
		payload["message"] = reason
	}
	evt := domain.Event{
		EventID:   uuid.NewString(),
		SessionID: call.SessionID,
		Type:      typ,
		Timestamp: time.Now().UTC(),
		Source:    domain.EventSourceMedia,
		Payload:   payload,
	}
	err := s.core.Publish(ctx, evt)
	if err != nil {
		s.log.Error("media event rejected by publisher", "eventId", evt.EventID, "sessionId", call.SessionID, "callId", call.ID, "type", typ, "err", err)
	}
	return err
}

func (s *Service) Control(ctx context.Context, callID, typ string) error {
	c, err := s.Get(callID)
	if err != nil {
		return err
	}
	if c.State != domain.CallStateActive {
		return fmt.Errorf("%w: call is not ACTIVE", domain.ErrInvalidArgument)
	}
	control, ok := s.asterisk.(ports.CallController)
	if !ok {
		return domain.ErrNotImplemented
	}
	return control.Control(ctx, callID, typ)
}
