package rtp_test

import (
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/rtp"
)

func TestMarshalParseRoundTrip(t *testing.T) {
	payload := []byte{0x01, 0x02, 0x03, 0x04}
	raw := rtp.Marshal(7, 160, 0xAABBCCDD, 0, false, payload)
	pkt, err := rtp.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if pkt.SequenceNumber != 7 || pkt.Timestamp != 160 || pkt.SSRC != 0xAABBCCDD {
		t.Fatalf("header mismatch: %+v", pkt)
	}
	if string(pkt.Payload) != string(payload) {
		t.Fatalf("payload mismatch")
	}
}

func TestParseRejectsShort(t *testing.T) {
	if _, err := rtp.Parse([]byte{0x80}); err == nil {
		t.Fatal("expected error")
	}
}

func TestParseExtensionCSRCPadding(t *testing.T) {
	raw := rtp.Marshal(1, 160, 1, 0, false, nil)
	raw[0] = 0xb1 // V2, padding, extension, one CSRC
	raw = append(raw, 0, 0, 0, 9, 0xbe, 0xde, 0, 1, 1, 2, 3, 4, 0x80, 0xff, 0, 2)
	pkt, err := rtp.Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if string(pkt.Payload) != string([]byte{0x80, 0xff}) {
		t.Fatalf("payload=%x", pkt.Payload)
	}
	for _, n := range []int{12, 15, 16, 19, 20, 23} {
		if _, err := rtp.Parse(raw[:n]); err == nil {
			t.Fatalf("accepted truncated length %d", n)
		}
	}
	raw[len(raw)-1] = 0
	if _, err := rtp.Parse(raw); err == nil {
		t.Fatal("accepted zero padding")
	}
	raw[len(raw)-1] = 255
	if _, err := rtp.Parse(raw); err == nil {
		t.Fatal("accepted excessive padding")
	}
}
