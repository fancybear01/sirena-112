package audio

// ULawEncode encodes a single PCM s16le sample to μ-law.
func ULawEncode(sample int16) byte {
	const (
		bias        = 0x84
		clip        = 32635
		signBit     = 0x80
	)
	sign := byte(0)
	if sample < 0 {
		sign = signBit
		sample = -sample
		if sample < 0 {
			sample = clip
		}
	}
	if sample > clip {
		sample = clip
	}
	sample = sample + bias
	exponent := byte(7)
	for expMask := int16(0x4000); (sample&expMask) == 0 && exponent > 0; exponent-- {
		expMask >>= 1
	}
	mantissa := byte((sample >> (exponent + 3)) & 0x0F)
	return ^(sign | (exponent << 4) | mantissa)
}

// ULawDecode decodes a μ-law byte to PCM s16le.
func ULawDecode(u byte) int16 {
	u = ^u
	sign := u & 0x80
	exponent := (u >> 4) & 0x07
	mantissa := u & 0x0F
	sample := ((int16(mantissa) << 3) + 0x84) << exponent
	sample -= 0x84
	if sign != 0 {
		return -sample
	}
	return sample
}

// PCMToULAW converts little-endian PCM16 mono to μ-law bytes.
func PCMToULAW(pcm []byte) []byte {
	out := make([]byte, len(pcm)/2)
	for i := 0; i+1 < len(pcm); i += 2 {
		sample := int16(uint16(pcm[i]) | uint16(pcm[i+1])<<8)
		out[i/2] = ULawEncode(sample)
	}
	return out
}

// ULAWToPCM converts μ-law bytes to little-endian PCM16 mono.
func ULAWToPCM(ulaw []byte) []byte {
	out := make([]byte, len(ulaw)*2)
	for i, b := range ulaw {
		s := ULawDecode(b)
		out[i*2] = byte(s)
		out[i*2+1] = byte(s >> 8)
	}
	return out
}
