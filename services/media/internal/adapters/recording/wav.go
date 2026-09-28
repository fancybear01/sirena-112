package recording

import (
	"encoding/binary"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sync"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
)

const SampleRate = 8000
const FrameSamples = 160
const FrameBytes = FrameSamples * 2 * 2 // 20 ms, stereo PCM16

var uuidName = regexp.MustCompile(`^[0-9a-fA-F-]{36}$`)
var ErrFull = errors.New("recording queue or duration limit exceeded")

type Info struct {
	SessionID  string
	CallID     string
	DurationMS int64
	Bytes      int64
}

type Recorder struct {
	mu     sync.Mutex
	file   *os.File
	part   string
	final  string
	info   Info
	frames int64
	max    int64
	queue  chan [FrameBytes]byte
	done   chan struct{}
	err    error
	closed bool
}

func New(root, sessionID, callID string, maxDuration time.Duration) (*Recorder, error) {
	if !uuidName.MatchString(sessionID) || !uuidName.MatchString(callID) {
		return nil, errors.New("recording requires UUID sessionId and callId")
	}
	if maxDuration <= 0 || maxDuration > 24*time.Hour {
		return nil, errors.New("invalid recording duration limit")
	}
	dir := filepath.Join(root, sessionID)
	if err := os.MkdirAll(dir, 0700); err != nil {
		return nil, fmt.Errorf("recording directory: %w", err)
	}
	part := filepath.Join(dir, callID+".wav.part")
	file, err := os.OpenFile(part, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return nil, fmt.Errorf("recording temporary file: %w", err)
	}
	if _, err = file.Write(make([]byte, 44)); err != nil {
		file.Close()
		os.Remove(part)
		return nil, err
	}
	r := &Recorder{file: file, part: part, final: filepath.Join(dir, callID+".wav"), info: Info{SessionID: sessionID, CallID: callID}, max: int64(maxDuration / (20 * time.Millisecond)), queue: make(chan [FrameBytes]byte, 100), done: make(chan struct{})}
	go r.write()
	return r, nil
}

// Frame never waits for the disk. A full queue fails the recording instead of
// delaying RTP or silently losing audio. Missing channels are PCM silence.
func (r *Recorder) Frame(in, out []byte) error {
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.closed || r.err != nil {
		return errors.New("recording stopped")
	}
	if r.frames >= r.max {
		r.err = ErrFull
		return r.err
	}
	var frame [FrameBytes]byte
	for i := 0; i < FrameSamples; i++ {
		if i < len(in) {
			binary.LittleEndian.PutUint16(frame[i*4:], uint16(audio.ULawDecode(in[i])))
		}
		if i < len(out) {
			binary.LittleEndian.PutUint16(frame[i*4+2:], uint16(audio.ULawDecode(out[i])))
		}
	}
	select {
	case r.queue <- frame:
		r.frames++
		return nil
	default:
		r.err = ErrFull
		return r.err
	}
}

func (r *Recorder) write() {
	defer close(r.done)
	for frame := range r.queue {
		if _, err := r.file.Write(frame[:]); err != nil {
			r.mu.Lock()
			r.err = err
			r.mu.Unlock()
			// Drain without writing so Stop can always finish.
			for range r.queue {
			}
			return
		}
	}
}

func (r *Recorder) Stop() (Info, error) {
	r.mu.Lock()
	if r.closed {
		info, err := r.info, r.err
		r.mu.Unlock()
		return info, err
	}
	r.closed = true
	close(r.queue)
	r.mu.Unlock()
	<-r.done
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.err != nil || r.frames == 0 {
		_ = r.file.Close()
		_ = os.Remove(r.part)
		if r.err == nil {
			r.err = errors.New("empty recording")
		}
		return Info{}, r.err
	}
	size := r.frames * FrameBytes
	header := wavHeader(uint32(size))
	if _, err := r.file.WriteAt(header[:], 0); err != nil {
		r.err = err
	}
	if r.err == nil {
		r.err = r.file.Sync()
	}
	if r.err == nil {
		r.err = r.file.Close()
	}
	if r.err == nil {
		r.err = os.Rename(r.part, r.final)
	}
	if r.err != nil {
		_ = r.file.Close()
		_ = os.Remove(r.part)
		return Info{}, r.err
	}
	r.info.DurationMS, r.info.Bytes = r.frames*20, size+44
	return r.info, nil
}

func wavHeader(size uint32) [44]byte {
	var h [44]byte
	copy(h[:], "RIFF")
	binary.LittleEndian.PutUint32(h[4:], size+36)
	copy(h[8:], "WAVEfmt ")
	binary.LittleEndian.PutUint32(h[16:], 16)
	binary.LittleEndian.PutUint16(h[20:], 1)
	binary.LittleEndian.PutUint16(h[22:], 2)
	binary.LittleEndian.PutUint32(h[24:], SampleRate)
	binary.LittleEndian.PutUint32(h[28:], SampleRate*4)
	binary.LittleEndian.PutUint16(h[32:], 4)
	binary.LittleEndian.PutUint16(h[34:], 16)
	copy(h[36:], "data")
	binary.LittleEndian.PutUint32(h[40:], size)
	return h
}

// Sweep removes stale incomplete files and expired final recordings.
func Sweep(root string, retention time.Duration) error {
	if retention <= 0 {
		return errors.New("invalid recording retention")
	}
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		if filepath.Ext(path) != ".wav" && filepath.Ext(path) != ".part" {
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if time.Since(info.ModTime()) > retention || (filepath.Ext(path) == ".part" && time.Since(info.ModTime()) > time.Hour) {
			return os.Remove(path)
		}
		return nil
	})
}

// Run at process start, before accepting calls. No active writer exists yet.
func RemoveIncomplete(root string) error {
	return filepath.WalkDir(root, func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if !entry.IsDir() && filepath.Ext(path) == ".part" {
			return os.Remove(path)
		}
		return nil
	})
}
