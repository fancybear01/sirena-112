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
