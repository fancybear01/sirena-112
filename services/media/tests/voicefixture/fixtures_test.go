package voicefixture

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/rtp"
	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
)

func fixture(t *testing.T, i int, ext string) []byte {
	t.Helper()
	b, err := os.ReadFile(fmt.Sprintf("testdata/%02d.%s", i, ext))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// Reference rate conversion for the fixture harness ONLY. ZOH upsampling and
// pair averaging make the sample clock explicit; this is not the #53 resampler.
func toPCM16k(payload []byte) []byte {
	pcm8 := audio.ULAWToPCM(payload)
	out := make([]byte, len(pcm8)*2)
	for i := 0; i < len(pcm8); i += 2 {
		copy(out[2*i:2*i+2], pcm8[i:i+2])
		copy(out[2*i+2:2*i+4], pcm8[i:i+2])
	}
	return out
}
func toULAW(pcm16 []byte) []byte {
	pcm8 := make([]byte, len(pcm16)/2)
	for i := 0; i < len(pcm16); i += 4 {
		a := int32(int16(binary.LittleEndian.Uint16(pcm16[i : i+2])))
		b := int32(int16(binary.LittleEndian.Uint16(pcm16[i+2 : i+4])))
		binary.LittleEndian.PutUint16(pcm8[i/2:i/2+2], uint16(int16((a+b)/2)))
	}
	return audio.PCMToULAW(pcm8)
}

func TestFixturesRoundTrip(t *testing.T) {
	raw, err := os.ReadFile("testdata/manifest.json")
	if err != nil {
		t.Fatal(err)
	}
	var manifest []struct {
		File       string
		Bytes      int
		DurationMs int
		SHA256     string
	}
	if err := json.Unmarshal(raw, &manifest); err != nil {
		t.Fatal(err)
	}
	if len(manifest) != 6 {
		t.Fatal("expected three RTP and three PCM frames")
	}
	for _, f := range manifest {
		b, err := os.ReadFile("testdata/" + f.File)
		if err != nil {
			t.Fatal(err)
		}
		hash := sha256.Sum256(b)
		if len(b) != f.Bytes || f.DurationMs != 20 || hex.EncodeToString(hash[:]) != f.SHA256 {
			t.Fatalf("fixture changed: %s", f.File)
		}
	}
	for i := 0; i < 3; i++ {
		raw := fixture(t, i, "rtp")
		pcm := fixture(t, i, "pcm")
		packet, err := rtp.Parse(raw)
		if err != nil {
			t.Fatal(err)
		}
		if len(raw) != 172 || len(packet.Payload) != 160 || len(pcm) != 640 {
			t.Fatal("frame boundary mismatch")
		}
		if packet.PayloadType != 0 || packet.SequenceNumber != uint16(65535+i) || packet.Timestamp != uint32(i*160) || packet.SSRC != 0x12345678 {
			t.Fatalf("header %d: %+v", i, packet)
		}
		if !bytes.Equal(toPCM16k(packet.Payload), pcm) {
			t.Fatalf("RTP→PCM frame %d differs from fixed golden", i)
		}
		payload := toULAW(pcm)
		reconstructed := rtp.Marshal(packet.SequenceNumber, packet.Timestamp, packet.SSRC, 0, false, payload)
		if !bytes.Equal(reconstructed, raw) {
			t.Fatalf("PCM→RTP frame %d differs", i)
		}
	}
	if !bytes.Equal(fixture(t, 0, "pcm"), make([]byte, 640)) {
		t.Fatal("silence is not PCM zero")
	}
	// Independent byte-order anchors: +988 = dc 03, -988 = 24 fc.
	pcm := fixture(t, 1, "pcm")
	if !bytes.Equal(pcm[:4], []byte{0xdc, 0x03, 0xdc, 0x03}) || !bytes.Equal(pcm[320:324], []byte{0x24, 0xfc, 0x24, 0xfc}) {
		t.Fatal("PCM must be signed little-endian")
	}
}
