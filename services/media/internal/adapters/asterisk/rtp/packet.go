package rtp

import (
	"encoding/binary"
	"fmt"
)

const headerSize = 12

// Packet is a parsed RTP packet (no audio logging).
type Packet struct {
	Version        byte
	Padding        bool
	Extension      bool
	CSRCCount      byte
	Marker         bool
	PayloadType    byte
	SequenceNumber uint16
	Timestamp      uint32
	SSRC           uint32
	Payload        []byte
}

// Parse validates and parses an RTP packet.
func Parse(buf []byte) (Packet, error) {
	if len(buf) < headerSize {
		return Packet{}, fmt.Errorf("rtp packet too short: %d", len(buf))
	}
	b0 := buf[0]
	version := b0 >> 6
	if version != 2 {
		return Packet{}, fmt.Errorf("unsupported rtp version: %d", version)
	}
	cc := b0 & 0x0F
	headerLen := headerSize + int(cc)*4
	if len(buf) < headerLen {
		return Packet{}, fmt.Errorf("rtp header truncated")
	}
	b1 := buf[1]
	p := Packet{
		Version:        version,
		Padding:        (b0 & 0x20) != 0,
		Extension:      (b0 & 0x10) != 0,
		CSRCCount:      cc,
		Marker:         (b1 & 0x80) != 0,
		PayloadType:    b1 & 0x7F,
		SequenceNumber: binary.BigEndian.Uint16(buf[2:4]),
		Timestamp:      binary.BigEndian.Uint32(buf[4:8]),
		SSRC:           binary.BigEndian.Uint32(buf[8:12]),
		Payload:        append([]byte(nil), buf[headerLen:]...),
	}
	return p, nil
}

// Marshal builds an RTP packet with the given header fields and payload.
func Marshal(seq uint16, ts uint32, ssrc uint32, payloadType byte, marker bool, payload []byte) []byte {
	out := make([]byte, headerSize+len(payload))
	out[0] = 0x80 // V=2
	out[1] = payloadType & 0x7F
	if marker {
		out[1] |= 0x80
	}
	binary.BigEndian.PutUint16(out[2:4], seq)
	binary.BigEndian.PutUint32(out[4:8], ts)
	binary.BigEndian.PutUint32(out[8:12], ssrc)
	copy(out[headerSize:], payload)
	return out
}
