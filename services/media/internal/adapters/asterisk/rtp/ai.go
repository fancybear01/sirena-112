package rtp

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"strconv"
	"sync"
	"time"

	aiadapter "github.com/fancybear01/sirena-112/services/media/internal/adapters/ai"
	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
	"github.com/fancybear01/sirena-112/services/media/internal/adapters/recording"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
)

type AIFactory struct {
	URL          string
	Log          *slog.Logger
	RecordingDir string
	MaxRecording time.Duration
}

func (f *AIFactory) Create(host string, port int) (ports.EchoSession, int, error) {
	addr, err := net.ResolveUDPAddr("udp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		return nil, 0, err
	}
	conn, err := net.ListenUDP("udp", addr)
	if err != nil {
		return nil, 0, err
	}
	s := &AISession{conn: conn, url: f.URL, log: f.Log, recordingDir: f.RecordingDir, maxRecording: f.MaxRecording, up: audio.NewResampler(), down: audio.NewResampler(), output: make(chan []byte, 500)}
	return s, conn.LocalAddr().(*net.UDPAddr).Port, nil
}

type AISession struct {
	conn              *net.UDPConn
	url               string
	log               *slog.Logger
	recordingDir      string
	maxRecording      time.Duration
	recorder          *recording.Recorder
	recordingInfo     *recording.Info
	recordingErr      error
	recordInput       []byte
	recordingMS       int64
	turnStartMS       int64
	turnEndMS         int64
	turnRecorded      bool
	mu                sync.Mutex
	inputMu           sync.Mutex
	ctx               context.Context
	cancel            context.CancelFunc
	wg                sync.WaitGroup
	stopOnce          sync.Once
	ws                *aiadapter.Client
	emit              func(ports.ARIEvent)
	req               ports.StartCallRequest
	peer              *net.UDPAddr
	started           bool
	stopped           bool
	activated         bool
	waiting           bool
	completed         bool
	dropping          bool
	hangupAfterAudio  bool
	input, outputTail []byte
	inputFrames       int
	output            chan []byte
	up, down          *audio.Resampler
	stats             ports.RTPStats
}

func (s *AISession) Start(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.started || s.stopped {
		return errors.New("media session already started/stopped")
	}
	s.started = true
	s.ctx, s.cancel = context.WithCancel(ctx)
	s.wg.Add(2)
	go s.read()
	go s.play()
	return nil
}
func (s *AISession) Activate(req ports.StartCallRequest, emit func(ports.ARIEvent)) error {
	s.mu.Lock()
	if s.stopped || !s.started {
		s.mu.Unlock()
		return errors.New("media session not running")
	}
	if s.activated {
		s.mu.Unlock()
		return nil
	}
	s.req, s.emit, s.activated = req, emit, true
	ctx, dir, maxRecording := s.ctx, s.recordingDir, s.maxRecording
	s.mu.Unlock()
	if dir != "" {
		recorder, err := recording.New(dir, req.SessionID, req.CallID, maxRecording)
		if err != nil {
			return err
		}
		s.mu.Lock()
		if s.stopped {
			s.mu.Unlock()
			_, _ = recorder.Stop()
			return errors.New("call ended during recording setup")
		}
		s.recorder = recorder
		s.mu.Unlock()
	}
	// Handshake may be slow; the UDP reader must remain free to drain packets.
	ws, err := aiadapter.Dial(ctx, aiadapter.Config{BaseURL: s.url}, req.SessionID, req.AISessionID, s.onAudio, s.onEvent, s.fail)
	if err != nil {
		return err
	}
	s.mu.Lock()
	if s.stopped {
		s.mu.Unlock()
		ws.Close()
		return errors.New("call ended during AI handshake")
	}
	s.ws = ws
	s.mu.Unlock()
	return nil
}
func (s *AISession) fail(err error) {
	s.mu.Lock()
	emit, req, stopped := s.emit, s.req, s.stopped
	s.mu.Unlock()
	if !stopped && emit != nil {
		emit(ports.ARIEvent{CallID: req.CallID, Type: "media.error", Payload: map[string]any{"message": err.Error()}})
	}
}
func (s *AISession) Stop(ctx context.Context) error {
	s.stopOnce.Do(func() {
		s.mu.Lock()
		s.stopped = true
		ws, cancel := s.ws, s.cancel
		s.mu.Unlock()
		if ws != nil {
			ws.Close()
		}
		if cancel != nil {
			cancel()
		}
		s.conn.Close()
		s.wg.Wait()
		if s.recorder != nil {
			info, err := s.recorder.Stop()
			s.mu.Lock()
			s.recordingErr = err
			if err == nil {
				s.recordingInfo = &info
			}
			s.mu.Unlock()
		}
		stats := s.Stats()
		s.log.Info("AI media stopped", "callId", s.req.CallID, "sessionId", s.req.SessionID, "aiSessionId", s.req.AISessionID, "rxPackets", stats.ReceivedPackets, "txPackets", stats.SentPackets)
	})
	return nil
}
func (s *AISession) Stats() ports.RTPStats { s.mu.Lock(); defer s.mu.Unlock(); return s.stats }
func (s *AISession) Recording() (*ports.RecordingInfo, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.recordingInfo == nil {
		return nil, s.recordingErr
	}
	i := s.recordingInfo
	return &ports.RecordingInfo{SessionID: i.SessionID, CallID: i.CallID, DurationMS: i.DurationMS, Bytes: i.Bytes}, s.recordingErr
}
func (s *AISession) Control(typ string) error {
	s.inputMu.Lock()
	defer s.inputMu.Unlock()
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.ws == nil || s.stopped {
		return errors.New("AI stream not active")
	}
	switch typ {
	case "input.flush":
		if s.waiting || len(s.output) > 0 {
			return errors.New("previous AI turn still playing")
		}
		if len(s.input) > 0 {
			frame := make([]byte, 640)
			copy(frame, s.input)
			if err := s.ws.SendPCM(frame); err != nil {
				return err
			}
			s.input = nil
			s.inputFrames++
		}
		if s.inputFrames == 0 {
			return errors.New("no audio to flush")
		}
		if err := s.ws.Control(typ); err != nil {
			return err
		}
		if s.turnRecorded && s.recordingMS > s.turnEndMS {
			s.turnEndMS = s.recordingMS
		}
		s.inputFrames = 0
		s.waiting = true
		s.completed = false
	case "response.cancel":
		if err := s.ws.Control(typ); err != nil {
			return err
		}
		s.dropping = true
		s.waiting = true
		s.completed = false
		s.outputTail = nil
		s.down = audio.NewResampler()
		for {
			select {
			case <-s.output:
			default:
				return nil
			}
		}
	default:
		return errors.New("unknown media control")
	}
	return nil
}
func (s *AISession) onAudio(pcm []byte) error {
	// Bound each critical section even if AI batches a long response.
	for offset := 0; offset < len(pcm); offset += 640 {
		s.mu.Lock()
		if s.stopped || s.dropping {
			s.mu.Unlock()
			return nil
		}
		if !s.waiting || s.completed {
			s.mu.Unlock()
			return errors.New("AI PCM outside response")
		}
		payload := s.down.DownPCM(pcm[offset:min(offset+640, len(pcm))])
		s.outputTail = append(s.outputTail, payload...)
		for len(s.outputTail) >= 160 {
			frame := append([]byte(nil), s.outputTail[:160]...)
			s.outputTail = s.outputTail[160:]
			select {
			case s.output <- frame:
			default:
				s.mu.Unlock()
				return errors.New("AI playback queue full")
			}
		}
		s.mu.Unlock()
	}
	return nil
}
func (s *AISession) onEvent(e map[string]any) error {
	typ, _ := e["type"].(string)
	s.mu.Lock()
	if s.stopped {
		s.mu.Unlock()
		return nil
	}
	emit, req := s.emit, s.req
	switch typ {
	case "response.completed":
		cancelled, _ := e["cancelled"].(bool)
		if s.dropping && !cancelled {
			s.mu.Unlock()
			return nil
		}
		s.dropping = false
		s.completed = true
		if len(s.outputTail) > 0 {
			frame := make([]byte, 160)
			for i := range frame {
				frame[i] = 0xff
			}
			copy(frame, s.outputTail)
			s.outputTail = nil
			select {
			case s.output <- frame:
			default:
				s.mu.Unlock()
				return errors.New("AI playback queue full")
			}
		}
		if len(s.output) == 0 {
			s.waiting = false
		}
	case "error":
		s.mu.Unlock()
		code, _ := e["code"].(string)
		return fmt.Errorf("AI error: %s", code)
	case "caller.state_changed":
		if hangup, _ := e["hangUp"].(bool); hangup {
			if len(s.output) > 0 {
				s.hangupAfterAudio = true
				s.mu.Unlock()
				return nil
			}
			s.mu.Unlock()
			emit(ports.ARIEvent{CallID: req.CallID, Type: "StasisEnd"})
			return nil
		}
	case "transcript.final", "transcript.partial", "response.started":
	default:
		s.mu.Unlock()
		return fmt.Errorf("unknown AI event type %q", typ)
	}
	s.mu.Unlock()
	if typ == "transcript.final" {
		payload := map[string]any{}
		for _, key := range []string{"text", "sequence", "startedAtMs", "endedAtMs", "simulated"} {
			if v, ok := e[key]; ok {
				payload[key] = v
			}
		}
		payload["finality"] = true
		if s.recorder != nil {
			s.mu.Lock()
			if s.turnRecorded {
				payload["recordingStartedAtMs"] = s.turnStartMS
				payload["recordingEndedAtMs"] = s.turnEndMS
				s.turnRecorded = false
			}
			s.mu.Unlock()
		}
		emit(ports.ARIEvent{CallID: req.CallID, Type: typ, Payload: payload})
	}
	return nil
}
func (s *AISession) read() {
	defer s.wg.Done()
	stop := context.AfterFunc(s.ctx, func() { s.conn.Close() })
	defer stop()
	buf := make([]byte, 65535)
	var last uint16
	var source uint32
	have := false
	for {
		n, peer, err := s.conn.ReadFromUDP(buf)
		if err != nil {
			return
		}
		p, err := Parse(buf[:n])
		if err != nil || p.PayloadType != 0 || len(p.Payload) == 0 {
			continue
		}
		s.inputMu.Lock()
		s.mu.Lock()
		if s.peer == nil {
			s.peer = peer
		}
		if !s.peer.IP.Equal(peer.IP) || s.peer.Port != peer.Port {
			s.mu.Unlock()
			s.inputMu.Unlock()
			continue
		}
		s.stats.ReceivedPackets++
		s.stats.BytesReceived += uint64(len(p.Payload))
		if have && p.SSRC == source {
			delta := int16(p.SequenceNumber - last)
			if delta <= 0 {
				s.mu.Unlock()
				s.inputMu.Unlock()
				continue
			}
			if delta > 1 {
				s.stats.SequenceGaps++
				s.stats.LostPackets += uint64(delta - 1)
			}
		}
		last, source, have = p.SequenceNumber, p.SSRC, true
		if s.recorder != nil && !s.stopped {
			s.recordInput = append(s.recordInput, p.Payload...)
			if len(s.recordInput) > 160*100 {
				s.mu.Unlock()
				s.inputMu.Unlock()
				s.fail(recording.ErrFull)
				return
			}
		}
		if s.ws == nil || s.waiting || s.stopped {
			s.mu.Unlock()
			s.inputMu.Unlock()
			continue
		}
		if s.recorder != nil {
			if !s.turnRecorded {
				s.turnStartMS = s.recordingMS
				s.turnRecorded = true
			}
			s.turnEndMS = s.recordingMS + 20
		}
		s.input = append(s.input, s.up.UpULAW(p.Payload)...)
		var sendErr error
		for len(s.input) >= 640 {
			if sendErr = s.ws.SendPCM(s.input[:640]); sendErr != nil {
				break
			}
			s.input = s.input[640:]
			s.inputFrames++
		}
		s.mu.Unlock()
		s.inputMu.Unlock()
		if sendErr != nil {
			s.fail(sendErr)
			return
		}
	}
}
func (s *AISession) play() {
	defer s.wg.Done()
	ticker := time.NewTicker(20 * time.Millisecond)
	defer ticker.Stop()
	var seed [10]byte
	_, _ = rand.Read(seed[:])
	seq := binary.BigEndian.Uint16(seed[:2])
	ts := binary.BigEndian.Uint32(seed[2:6])
	ssrc := binary.BigEndian.Uint32(seed[6:])
	for {
		select {
		case <-s.ctx.Done():
			return
		case <-ticker.C:
			ts += 160 // RTP sampling clock also advances during silence between turns.
			s.mu.Lock()
			var inputFrame []byte
			if len(s.recordInput) >= 160 {
				inputFrame = s.recordInput[:160]
				s.recordInput = s.recordInput[160:]
			}
			var outputFrame []byte
			if s.peer == nil || s.stopped {
				if s.recorder != nil && !s.stopped {
					if err := s.recordTick(inputFrame, nil); err != nil {
						s.mu.Unlock()
						s.fail(err)
						return
					}
				}
				s.mu.Unlock()
				continue
			}
			select {
			case payload := <-s.output:
				outputFrame = payload
				raw := Marshal(seq, ts, ssrc, 0, false, payload)
				seq++
				_ = s.conn.SetWriteDeadline(time.Now().Add(10 * time.Millisecond))
				_, err := s.conn.WriteToUDP(raw, s.peer)
				if err == nil {
					s.stats.SentPackets++
					s.stats.BytesSent += uint64(len(payload))
				}
				if s.completed && len(s.output) == 0 {
					s.waiting = false
				}
				endCall := s.hangupAfterAudio && len(s.output) == 0
				emit, callID := s.emit, s.req.CallID
				if endCall {
					s.hangupAfterAudio = false
				}
				if s.recorder != nil {
					if err := s.recordTick(inputFrame, outputFrame); err != nil {
						s.mu.Unlock()
						s.fail(err)
						return
					}
				}
				s.mu.Unlock()
				if err != nil {
					s.fail(errors.New("RTP playback write failed"))
					return
				}
				if endCall {
					emit(ports.ARIEvent{CallID: callID, Type: "StasisEnd"})
					return
				}
			default:
				if s.recorder != nil {
					if err := s.recordTick(inputFrame, nil); err != nil {
						s.mu.Unlock()
						s.fail(err)
						return
					}
				}
				s.mu.Unlock()
			}
		}
	}
}

// Called with s.mu held by the 20 ms playback clock.
func (s *AISession) recordTick(in, out []byte) error {
	if err := s.recorder.Frame(in, out); err != nil {
		return err
	}
	s.recordingMS += 20
	return nil
}
