package audio

import (
	"encoding/binary"
	"math"
)

// Resampler is a stateful 2:1 FIR converter. The 63-tap windowed-sinc low-pass
// operates at 16 kHz (cutoff 3.4 kHz); history and decimation phase span packets.
// Each direction owns its own instance. Group delay is 31 samples at 16 kHz.
type Resampler struct {
	taps       [63]float64
	history    [63]float64
	pos, phase int
}

func NewResampler() *Resampler {
	r := &Resampler{}
	sum := 0.0
	for i := range r.taps {
		x := float64(i - 31)
		v := 2 * 3400.0 / 16000
		if x != 0 {
			v = math.Sin(2*math.Pi*3400/16000*x) / (math.Pi * x)
		}
		v *= 0.54 - 0.46*math.Cos(2*math.Pi*float64(i)/62)
		r.taps[i] = v
		sum += v
	}
	for i := range r.taps {
		r.taps[i] /= sum
	}
	return r
}
func (r *Resampler) sample(x float64) float64 {
	r.history[r.pos] = x
	y := 0.0
	for i, c := range r.taps {
		y += c * r.history[(r.pos-i+63)%63]
	}
	r.pos = (r.pos + 1) % 63
	return y
}
func appendSample(out []byte, v float64) []byte {
	v = math.Max(-32768, math.Min(32767, math.Round(v)))
	return binary.LittleEndian.AppendUint16(out, uint16(int16(v)))
}
func (r *Resampler) UpULAW(payload []byte) []byte {
	out := make([]byte, 0, len(payload)*4)
	for _, v := range payload {
		out = appendSample(out, 2*r.sample(float64(ULawDecode(v))))
		out = appendSample(out, 2*r.sample(0))
	}
	return out
}
func (r *Resampler) DownPCM(pcm []byte) []byte {
	out := make([]byte, 0, len(pcm)/4)
	for i := 0; i+1 < len(pcm); i += 2 {
		v := r.sample(float64(int16(binary.LittleEndian.Uint16(pcm[i:]))))
		r.phase ^= 1
		if r.phase == 0 {
			v = math.Max(-32768, math.Min(32767, math.Round(v)))
			out = append(out, ULawEncode(int16(v)))
		}
	}
	return out
}
