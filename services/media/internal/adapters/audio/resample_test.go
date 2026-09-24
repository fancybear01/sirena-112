package audio

import (
	"bytes"
	"encoding/binary"
	"math"
	"testing"
)

func TestResamplerContinuityAndSilence(t *testing.T) {
	input := make([]byte, 480)
	for i := range input {
		input[i] = ULawEncode(int16(12000 * math.Sin(2*math.Pi*float64(i)/16)))
	}
	whole := NewResampler().UpULAW(input)
	r := NewResampler()
	var chunks []byte
	for i := 0; i < len(input); i += 160 {
		part := r.UpULAW(input[i : i+160])
		if len(part) != 640 {
			t.Fatal("wrong frame length")
		}
		chunks = append(chunks, part...)
	}
	if !bytes.Equal(whole, chunks) {
		t.Fatal("history reset at packet boundary")
	}
	down := NewResampler()
	var parts []byte
	for i := 0; i < len(whole); i += 640 {
		parts = append(parts, down.DownPCM(whole[i:i+640])...)
	}
	if !bytes.Equal(parts, NewResampler().DownPCM(whole)) {
		t.Fatal("decimation discontinuity")
	}
	silence := bytes.Repeat([]byte{0xff}, 160)
	pcm := NewResampler().UpULAW(silence)
	if !bytes.Equal(pcm, make([]byte, 640)) || !bytes.Equal(NewResampler().DownPCM(pcm), silence) {
		t.Fatal("silence changed")
	}
	// After filter delay, the signal should retain useful amplitude with bounded error.
	var mse, energy float64
	for i := 100; i < len(parts); i++ {
		a := float64(ULawDecode(input[i-31]))
		b := float64(ULawDecode(parts[i]))
		mse += (a - b) * (a - b)
		energy += a * a
	}
	if mse/energy > 0.1 {
		t.Fatalf("roundtrip distortion=%f", mse/energy)
	}
}
func TestDownsamplerRejectsAliasing(t *testing.T) {
	rms := func(hz float64) float64 {
		pcm := make([]byte, 3200*2)
		for i := 0; i < 3200; i++ {
			binary.LittleEndian.PutUint16(pcm[2*i:], uint16(int16(12000*math.Sin(2*math.Pi*hz*float64(i)/16000))))
		}
		out := NewResampler().DownPCM(pcm)
		sum := 0.0
		for _, v := range out[100:] {
			x := float64(ULawDecode(v))
			sum += x * x
		}
		return math.Sqrt(sum / float64(len(out)-100))
	}
	pass, stop := rms(1000), rms(6000)
	if pass < 7000 || stop/pass > 0.02 {
		t.Fatalf("pass RMS=%f alias RMS=%f", pass, stop)
	}
}
