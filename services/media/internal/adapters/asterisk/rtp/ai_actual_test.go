package rtp

import (
	"bytes"
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/google/uuid"
)

func TestActualAIProtocol(t *testing.T) {
	python := os.Getenv("MEDIA_AI_PYTHON")
	if python == "" {
		t.Skip("set MEDIA_AI_PYTHON to a Python with services/ai dependencies")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	listener.Close()
	args := []string{"../../../../scripts/ai-test-server.py", "--port", strconv.Itoa(port)}
	real := os.Getenv("MEDIA_AI_REAL") == "1"
	if real {
		args = append(args, "--real")
	}
	proc := exec.Command(python, args...)
	proc.Stderr = os.Stderr
	if err := proc.Start(); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = proc.Process.Kill(); _ = proc.Wait() })
	base := fmt.Sprintf("http://127.0.0.1:%d", port)
	httpClient := &http.Client{Timeout: 2 * time.Second}
	deadline := time.Now().Add(30 * time.Second)
	ready := false
	for time.Now().Before(deadline) {
		resp, err := httpClient.Get(base + "/health")
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == 200 {
				ready = true
				break
			}
		}
		time.Sleep(50 * time.Millisecond)
	}
	if !ready {
		t.Fatal("actual AI did not become ready")
	}
	post := func(path string, body any) map[string]any {
		t.Helper()
		b, _ := json.Marshal(body)
		resp, err := httpClient.Post(base+path, "application/json", bytes.NewReader(b))
		if err != nil {
			t.Fatal(err)
		}
		defer resp.Body.Close()
		var result map[string]any
		if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
			t.Fatal(err)
		}
		if resp.StatusCode >= 300 {
			t.Fatalf("AI status %d: %v", resp.StatusCode, result)
		}
		return result
	}
	generated := post("/ai/scenarios/generate", map[string]any{"category": "FIRE", "count": 4})
	scenario := generated["scenarios"].([]any)[0]
	recordings := t.TempDir()
	for call := 0; call < 2; call++ {
		sessionID := uuid.NewString()
		created := post("/ai/voice/sessions", map[string]any{"sessionId": sessionID, "scenario": scenario})
		aiID := created["aiSessionId"].(string)
		if real && created["speechSimulated"] != false {
			t.Fatal("real model run requested but speech is simulated/unavailable")
		}
		if !real && created["speech"] != "scripted+silence" {
			t.Fatal(created)
		}
		callID := uuid.NewString()
		sess, port, err := (&AIFactory{URL: fmt.Sprintf("ws://127.0.0.1:%d", port), Log: slog.Default(), RecordingDir: recordings, MaxRecording: time.Minute}).Create("127.0.0.1", 0)
		if err != nil {
			t.Fatal(err)
		}
		s := sess.(*AISession)
		s.Start(context.Background())
		defer s.Stop(context.Background())
		events := make(chan ports.ARIEvent, 16)
		if err := s.Activate(ports.StartCallRequest{CallID: callID, SessionID: sessionID, AISessionID: aiID}, func(e ports.ARIEvent) { events <- e }); err != nil {
			t.Fatal(err)
		}
		peer, err := net.DialUDP("udp", nil, &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: port})
		if err != nil {
			t.Fatal(err)
		}
		seq := uint16(0)
		var spans [][2]int64
		for turn := 0; turn < 2; turn++ {
			input := bytes.Repeat([]byte{255}, 480)
			if real {
				name := []string{"operator-01-address.wav", "operator-02-victims.wav"}[turn]
				raw, err := os.ReadFile("../../../../../ai/tests/fixtures/voice/" + name)
				if err != nil {
					t.Fatal(err)
				}
				pcm := wavData(t, raw)
				input = audio.NewResampler().DownPCM(pcm)
			}
			count := 0
			for offset := 0; offset < len(input); offset += 160 {
				payload := bytes.Repeat([]byte{255}, 160)
				copy(payload, input[offset:min(offset+160, len(input))])
				peer.Write(Marshal(seq, uint32(seq)*160, 9, 0, false, payload))
				seq++
				count++
				time.Sleep(20 * time.Millisecond)
			}
			eventually(t, func() bool { s.mu.Lock(); defer s.mu.Unlock(); return s.inputFrames == count })
			if err := s.Control("input.flush"); err != nil {
				t.Fatal(err)
			}
			select {
			case e := <-events:
				if e.Type != "transcript.final" {
					t.Fatalf("AI failure: %+v", e)
				}
				if e.Payload["simulated"] != !real {
					t.Fatal("wrong simulated flag")
				}
				start, okStart := e.Payload["recordingStartedAtMs"].(int64)
				end, okEnd := e.Payload["recordingEndedAtMs"].(int64)
				if !okStart || !okEnd || start >= end {
					t.Fatalf("transcript has no WAV position: %+v", e.Payload)
				}
				spans = append(spans, [2]int64{start, end})
			case <-time.After(30 * time.Second):
				t.Fatal("no transcript")
			}
			frames := 0
			var prev Packet
			var first, last time.Time
			for {
				buf := make([]byte, 2048)
				peer.SetReadDeadline(time.Now().Add(200 * time.Millisecond))
				n, err := peer.Read(buf)
				if err != nil {
					if ne, ok := err.(net.Error); ok && ne.Timeout() {
						s.mu.Lock()
						done := s.completed && !s.waiting
						s.mu.Unlock()
						if done {
							break
						}
					}
					t.Fatalf("RTP receive: %v", err)
				}
				packet, err := Parse(buf[:n])
				if err != nil {
					t.Fatal(err)
				}
				if len(packet.Payload) != 160 {
					t.Fatal("incorrect RTP frame")
				}
				if !real && !bytes.Equal(packet.Payload, bytes.Repeat([]byte{255}, 160)) {
					t.Fatal("scripted answer is not silence")
				}
				if frames > 0 && (packet.SequenceNumber != prev.SequenceNumber+1 || packet.Timestamp != prev.Timestamp+160 || packet.SSRC != prev.SSRC) {
					t.Fatal("RTP header discontinuity")
				}
				now := time.Now()
				if frames == 0 {
					first = now
				}
				last = now
				prev = packet
				frames++
			}
			if frames < 2 || last.Sub(first) < time.Duration(frames-1)*15*time.Millisecond {
				t.Fatal("answer was sent as a burst")
			}
			t.Logf("call=%d turn=%d inputFrames=%d outputRTP=%d elapsed=%s simulated=%v", call+1, turn+1, count, frames, last.Sub(first), !real)
		}
		s.Stop(context.Background())
		info, err := s.Recording()
		if err != nil || info == nil || info.CallID != callID || info.SessionID != sessionID || info.DurationMS < 100 || info.Bytes != 44+info.DurationMS*32 {
			t.Fatalf("recording metadata: %+v %v", info, err)
		}
		if len(spans) != 2 || spans[0][1] >= spans[1][0] || spans[1][1] > info.DurationMS {
			t.Fatalf("transcript/WAV timeline mismatch: %v, duration %d", spans, info.DurationMS)
		}
		wave, err := os.ReadFile(filepath.Join(recordings, sessionID, callID+".wav"))
		if err != nil || len(wave) < 44 || len(wave) != int(info.Bytes) || string(wave[:4]) != "RIFF" {
			t.Fatalf("recording not playable: %v, size %d", err, len(wave))
		}
		peer.Close()
		req, _ := http.NewRequest(http.MethodDelete, base+"/ai/voice/sessions/"+aiID, nil)
		resp, err := httpClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}
}
func wavData(t *testing.T, b []byte) []byte {
	t.Helper()
	if len(b) < 12 || string(b[:4]) != "RIFF" {
		t.Fatal("invalid WAV")
	}
	for pos := 12; pos+8 <= len(b); {
		n := int(binary.LittleEndian.Uint32(b[pos+4 : pos+8]))
		if pos+8+n > len(b) {
			t.Fatal("truncated WAV")
		}
		if string(b[pos:pos+4]) == "data" {
			return b[pos+8 : pos+8+n]
		}
		pos += 8 + n + (n % 2)
	}
	t.Fatal("WAV has no data")
	return nil
}
