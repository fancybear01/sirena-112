package audio_test

import (
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
)

func TestULAWRoundTripSilence(t *testing.T) {
	pcm := make([]byte, 320) // 160 samples
	ulaw := audio.PCMToULAW(pcm)
	if len(ulaw) != 160 {
		t.Fatalf("ulaw len %d", len(ulaw))
	}
	out := audio.ULAWToPCM(ulaw)
	if len(out) != 320 {
		t.Fatalf("pcm len %d", len(out))
	}
}
