package core

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

type HTTPPublisher struct {
	url    string
	http   *http.Client
	log    *slog.Logger
	token  string
	queue  chan []byte
	mu     sync.Mutex
	closed bool
	done   chan struct{}
	ctx    context.Context
	cancel context.CancelFunc
}

func NewHTTPPublisher(base string, log *slog.Logger) *HTTPPublisher {
	ctx, cancel := context.WithCancel(context.Background())
	p := &HTTPPublisher{url: strings.TrimRight(base, "/") + "/internal/v1/media/events", http: &http.Client{Timeout: 2 * time.Second}, log: log, token: os.Getenv("CORE_MEDIA_SERVICE_TOKEN"), queue: make(chan []byte, 256), done: make(chan struct{}), ctx: ctx, cancel: cancel}
	go p.run()
	return p
}

// Serialize before enqueue so later payload mutations cannot change a retry.
func (p *HTTPPublisher) Publish(ctx context.Context, event domain.Event) error {
	data, err := json.Marshal(event)
	if err != nil {
		return err
	}
	p.mu.Lock()
	defer p.mu.Unlock()
	if p.closed {
		return errors.New("Core publisher closed")
	}
	select {
	case p.queue <- data:
		return nil
	default:
		return errors.New("Core event queue full")
	}
}
func (p *HTTPPublisher) run() {
	defer close(p.done)
	for data := range p.queue {
		if p.ctx.Err() != nil {
			return
		}
		var err error
		for attempt := 0; attempt < 3; attempt++ {
			var retry bool
			retry, err = p.post(data)
			if err == nil || !retry {
				break
			}
			select {
			case <-p.ctx.Done():
				return
			case <-time.After(time.Duration(attempt+1) * 200 * time.Millisecond):
			}
		}
		if err != nil {
			p.log.Error("Core event delivery failed", "err", err)
		}
	}
}
func (p *HTTPPublisher) post(data []byte) (bool, error) {
	req, err := http.NewRequestWithContext(p.ctx, http.MethodPost, p.url, bytes.NewReader(data))
	if err != nil {
		return false, err
	}
	req.Header.Set("Content-Type", "application/json")
	if p.token != "" {
		req.Header.Set("Authorization", "Bearer "+p.token)
	}
	resp, err := p.http.Do(req)
	if err != nil {
		return true, err
	}
	defer resp.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 4096))
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		return false, nil
	}
	return resp.StatusCode >= 500 || resp.StatusCode == 429 || resp.StatusCode == 409, fmt.Errorf("Core ingest status %d", resp.StatusCode)
}
func (p *HTTPPublisher) Close(ctx context.Context) error {
	p.mu.Lock()
	if !p.closed {
		p.closed = true
		close(p.queue)
	}
	p.mu.Unlock()
	select {
	case <-p.done:
		p.cancel()
		return nil
	case <-ctx.Done():
		p.cancel()
		<-p.done
		return ctx.Err()
	}
}
