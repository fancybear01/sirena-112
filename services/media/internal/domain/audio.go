package domain

// Canonical PCM frame for Media <-> AI (contracts/media-ai.md).
const (
	PCMSampleRateHz   = 16000
	PCMChannels       = 1
	PCMFrameDurationMs = 20
	PCMBytesPerSample = 2
	PCMFrameBytes     = PCMSampleRateHz * PCMChannels * PCMBytesPerSample * PCMFrameDurationMs / 1000 // 640
)

// RTPCodecULAW is the MVP codec between Asterisk and Media.
const (
	RTPCodecULAW      = "ulaw"
	RTPSampleRateHz   = 8000
	RTPPayloadTypeULAW = 0
	RTPFrameDurationMs = 20
	RTPFrameSamples   = RTPSampleRateHz * RTPFrameDurationMs / 1000 // 160
)
