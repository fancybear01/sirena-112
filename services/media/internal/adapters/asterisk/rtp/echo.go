package rtp

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"log/slog"
	"net"
	"strconv"
	"sync"
	"sync/atomic"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/audio"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

// EchoSession echoes μ-law RTP payloads back to the peer.
type EchoSession struct {
	conn    *net.UDPConn
	log     *slog.Logger
	cancel  context.CancelFunc
	mu      sync.Mutex
	started bool
	stopped bool
	wg      sync.WaitGroup

	received atomic.Uint64
	sent     atomic.Uint64
	lost     atomic.Uint64
	gaps     atomic.Uint64
	bytesIn  atomic.Uint64
	bytesOut atomic.Uint64
}

// Factory creates echo sessions.
type Factory struct {
	Log *slog.Logger
}

func (f *Factory) Create(listenHost string, listenPort int) (ports.EchoSession, int, error) {
	addr, err := net.ResolveUDPAddr("udp", net.JoinHostPort(listenHost, strconv.Itoa(listenPort)))
	if err != nil {
		return nil, 0, err
	}
	conn, err := net.ListenUDP("udp", addr)
	if err != nil {
		return nil, 0, err
	}
	bound := conn.LocalAddr().(*net.UDPAddr).Port
	s := &EchoSession{conn: conn, log: f.Log}
	return s, bound, nil
}

func (s *EchoSession) Start(ctx context.Context) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.started || s.stopped {
		return fmt.Errorf("rtp session already started or stopped")
	}
	s.started = true
	ctx, s.cancel = context.WithCancel(ctx)
	_ = s.conn.SetReadDeadline(time.Time{})
	s.wg.Add(1)
	go s.loop(ctx)
	return nil
}

func (s *EchoSession) Stop(ctx context.Context) error {
	_ = ctx
	s.mu.Lock()
	s.stopped = true
	if s.cancel != nil {
		s.cancel()
	}
	_ = s.conn.SetReadDeadline(time.Now())
	_ = s.conn.Close()
	s.wg.Wait()
	s.mu.Unlock()
	stats := s.Stats()
	s.log.Info("rtp echo stopped",
		"rxPackets", stats.ReceivedPackets,
		"txPackets", stats.SentPackets,
		"lostPackets", stats.LostPackets,
		"sequenceGaps", stats.SequenceGaps,
		"bytesReceived", stats.BytesReceived,
		"bytesSent", stats.BytesSent,
	)
	return nil
}

func (s *EchoSession) Stats() ports.RTPStats {
	return ports.RTPStats{
		ReceivedPackets: s.received.Load(),
		SentPackets:     s.sent.Load(),
		LostPackets:     s.lost.Load(),
		SequenceGaps:    s.gaps.Load(),
		BytesReceived:   s.bytesIn.Load(),
		BytesSent:       s.bytesOut.Load(),
	}
}

func (s *EchoSession) loop(ctx context.Context) {
	defer s.wg.Done()
	closeOnCancel := context.AfterFunc(ctx, func() { _ = s.conn.Close() })
	defer closeOnCancel()
	buf := make([]byte, 2048)
	var seed [10]byte
	_, _ = rand.Read(seed[:])
	ssrc := binary.BigEndian.Uint32(seed[:4])
	var peer *net.UDPAddr
	var sourceSSRC uint32
	var lastSeq uint16
	hasSeq := false
	outSeq := binary.BigEndian.Uint16(seed[4:6])
	outTS := binary.BigEndian.Uint32(seed[6:10])

	for {
		n, addr, err := s.conn.ReadFromUDP(buf)
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
				if ne, ok := err.(net.Error); ok && ne.Timeout() {
					return
				}
				s.log.Debug("rtp read error", "err", err)
				return
			}
		}
		pkt, err := Parse(buf[:n])
		if err != nil {
			continue
		}
		if pkt.PayloadType != domain.RTPPayloadTypeULAW {
			continue
		}

		if len(pkt.Payload) == 0 {
			continue
		}
		// One externalMedia peer per socket. Do not mix unrelated RTP sources.
		if peer == nil {
			peer = addr
		}
		if !peer.IP.Equal(addr.IP) || peer.Port != addr.Port || peer.Zone != addr.Zone {
			continue
		}
		s.received.Add(1)
		s.bytesIn.Add(uint64(len(pkt.Payload)))
		if !hasSeq || sourceSSRC != pkt.SSRC {
			sourceSSRC, lastSeq, hasSeq = pkt.SSRC, pkt.SequenceNumber, true
		} else {
			delta := int16(pkt.SequenceNumber - lastSeq)
			if delta <= 0 {
				continue
			} // duplicate or late packet; keep the high-water mark
			if delta > 1 {
				s.gaps.Add(1)
				s.lost.Add(uint64(delta - 1))
			}
			lastSeq = pkt.SequenceNumber
		}

		// Echo: decode/encode keeps the pipeline honest for later AI PCM path.
		pcm := audio.ULAWToPCM(pkt.Payload)
		ulaw := audio.PCMToULAW(pcm)
		outSeq++
		out := Marshal(outSeq, outTS, ssrc, domain.RTPPayloadTypeULAW, false, ulaw)
		outTS += uint32(len(ulaw)) // PCMU: one sample per byte, including non-20ms packets
		if _, err := s.conn.WriteToUDP(out, addr); err != nil {
			continue
		}
		s.sent.Add(1)
		s.bytesOut.Add(uint64(len(ulaw)))
	}
}
