package rtp

import (
	"context"
	"log/slog"
	"net"
	"testing"
	"time"
)

func TestEchoSequenceTimestampAndCancellation(t *testing.T) {
	session, port, err := (&Factory{Log: slog.Default()}).Create("127.0.0.1", 0)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	if err := session.Start(ctx); err != nil {
		t.Fatal(err)
	}
	defer session.Stop(context.Background())
	if err := session.Start(ctx); err == nil {
		t.Fatal("double start accepted")
	}
	peer, err := net.DialUDP("udp", nil, &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: port})
	if err != nil {
		t.Fatal(err)
	}
	defer peer.Close()
	exchange := func(seq uint16, size int) Packet {
		t.Helper()
		payload := make([]byte, size)
		for i := range payload {
			payload[i] = 0xff
		}
		if _, err := peer.Write(Marshal(seq, 0, 7, 0, false, payload)); err != nil {
			t.Fatal(err)
		}
		_ = peer.SetReadDeadline(time.Now().Add(time.Second))
		buf := make([]byte, 2048)
		n, err := peer.Read(buf)
		if err != nil {
			t.Fatal(err)
		}
		p, err := Parse(buf[:n])
		if err != nil {
			t.Fatal(err)
		}
		return p
	}
	first := exchange(65535, 80)
	second := exchange(0, 240)
	if second.Timestamp-first.Timestamp != 80 {
		t.Fatalf("timestamp delta=%d", second.Timestamp-first.Timestamp)
	}
	// Duplicate and late packets must neither echo nor inflate lost packet counts.
	_, _ = peer.Write(Marshal(0, 0, 7, 0, false, []byte{0xff}))
	_, _ = peer.Write(Marshal(65535, 0, 7, 0, false, []byte{0xff}))
	third := exchange(2, 160)
	if third.Timestamp-second.Timestamp != 240 {
		t.Fatalf("timestamp delta=%d", third.Timestamp-second.Timestamp)
	}
	// UDP response can reach us just before the atomic sent counter is updated.
	deadline := time.Now().Add(time.Second)
	for session.Stats().SentPackets < 3 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	stats := session.Stats()
	if stats.LostPackets != 1 || stats.SequenceGaps != 1 || stats.SentPackets != 3 {
		t.Fatalf("stats=%+v", stats)
	}
	cancel()
	done := make(chan struct{})
	go func() { session.(*EchoSession).wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("reader did not stop on cancellation")
	}
	if err := session.Stop(context.Background()); err != nil {
		t.Fatal(err)
	}
	conn, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.ParseIP("127.0.0.1"), Port: port})
	if err != nil {
		t.Fatalf("port leaked: %v", err)
	}
	conn.Close()
}
