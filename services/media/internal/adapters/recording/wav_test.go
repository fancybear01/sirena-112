package recording

import (
	"encoding/binary"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestTwoCallsPlayableWAVAndRetention(t *testing.T) {
	root := t.TempDir()
	for call := 0; call < 2; call++ {
		sessionID, callID := uuid.NewString(), uuid.NewString()
		r, err := New(root, sessionID, callID, time.Minute)
		if err != nil {
			t.Fatal(err)
		}
		left, right := byte(0xff), byte(0x00)
		if call == 1 {
			left, right = 0x00, 0xff
		}
		for i := 0; i < 5; i++ {
			in, out := make([]byte, 160), make([]byte, 160)
			for j := range in {
				in[j], out[j] = left, right
			}
			if err := r.Frame(in, out); err != nil {
				t.Fatal(err)
			}
		}
		info, err := r.Stop()
		if err != nil {
			t.Fatal(err)
		}
		if info.SessionID != sessionID || info.CallID != callID || info.DurationMS != 100 || info.Bytes != 44+5*FrameBytes {
			t.Fatal(info)
		}
		path := filepath.Join(root, sessionID, callID+".wav")
		wave, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if string(wave[:4]) != "RIFF" || string(wave[8:12]) != "WAVE" || binary.LittleEndian.Uint16(wave[22:24]) != 2 || binary.LittleEndian.Uint32(wave[24:28]) != 8000 || binary.LittleEndian.Uint32(wave[40:44]) != 5*FrameBytes {
			t.Fatal("invalid WAV header")
		}
		if binary.LittleEndian.Uint16(wave[44:46]) == binary.LittleEndian.Uint16(wave[46:48]) {
			t.Fatal("channels mixed")
		}
		if _, err := os.Stat(path + ".part"); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("temporary file remained")
		}
		if call == 0 {
			old := time.Now().Add(-8 * 24 * time.Hour)
			if err := os.Chtimes(path, old, old); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := Sweep(root, 7*24*time.Hour); err != nil {
		t.Fatal(err)
	}
	paths, err := filepath.Glob(filepath.Join(root, "*", "*.wav"))
	if err != nil || len(paths) != 1 {
		t.Fatalf("remaining recordings: %v, %v", paths, err)
	}
}

func TestUnavailableStorageAndIncompleteCleanup(t *testing.T) {
	root := t.TempDir()
	blocked := filepath.Join(root, "blocked")
	if err := os.WriteFile(blocked, []byte("x"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := New(blocked, uuid.NewString(), uuid.NewString(), time.Second); err == nil {
		t.Fatal("unavailable storage accepted")
	}
	sessionID, callID := uuid.NewString(), uuid.NewString()
	r, err := New(root, sessionID, callID, 20*time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Frame([]byte{0xff}, nil); err != nil {
		t.Fatal(err)
	}
	if !errors.Is(r.Frame(nil, nil), ErrFull) {
		t.Fatal("duration limit ignored")
	}
	if _, err := r.Stop(); !errors.Is(err, ErrFull) {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(root, sessionID, callID+".wav.part")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("incomplete file remained")
	}
	stale := filepath.Join(root, "orphan.wav.part")
	if err := os.WriteFile(stale, []byte("partial"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := RemoveIncomplete(root); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(stale); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("orphan remained")
	}
}
