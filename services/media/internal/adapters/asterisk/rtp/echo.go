package rtp

import (
	"context"
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
	conn   *net.UDPConn
	log    *slog.Logger
	cancel context.CancelFunc
	wg     sync.WaitGroup

	received atomic.Uint64
	sent     atomic.Uint64
	lost     atomic.Uint64
	gaps     atomic.Uint64
	bytesIn  atomic.Uint64
	bytesOut atomic.Uint64

	lastSeq atomic.Uint32
	hasSeq  atomic.Bool
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
	ctx, s.cancel = context.WithCancel(ctx)
	_ = s.conn.SetReadDeadline(time.Time{})
	s.wg.Add(1)
	go s.loop(ctx)
	return nil
}

func (s *EchoSession) Stop(ctx context.Context) error {
	_ = ctx
	if s.cancel != nil {
		s.cancel()
	}
	_ = s.conn.SetReadDeadline(time.Now())
	_ = s.conn.Close()
	s.wg.Wait()
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
	buf := make([]byte, 2048)
	var ssrc uint32 = 0x5E1E4A11
	var outSeq uint16
	var outTS uint32

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

		s.received.Add(1)
		s.bytesIn.Add(uint64(len(pkt.Payload)))
		if s.hasSeq.Load() {
			prev := uint16(s.lastSeq.Load())
			expected := prev + 1
			if pkt.SequenceNumber != expected {
				gap := uint16(pkt.SequenceNumber - expected)
				s.gaps.Add(1)
				s.lost.Add(uint64(gap))
			}
		} else {
			s.hasSeq.Store(true)
		}
		s.lastSeq.Store(uint32(pkt.SequenceNumber))

		// Echo: decode/encode keeps the pipeline honest for later AI PCM path.
		pcm := audio.ULAWToPCM(pkt.Payload)
		ulaw := audio.PCMToULAW(pcm)
		outSeq++
		outTS += uint32(domain.RTPFrameSamples)
		out := Marshal(outSeq, outTS, ssrc, domain.RTPPayloadTypeULAW, false, ulaw)
		if _, err := s.conn.WriteToUDP(out, addr); err != nil {
			continue
		}
		s.sent.Add(1)
		s.bytesOut.Add(uint64(len(ulaw)))
	}
}
