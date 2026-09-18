package core

import (
	"context"
	"log/slog"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

// LoggingPublisher is an MVP CoreEventPublisher that logs events.
// Replace with HTTP client when Core exposes an ingest endpoint.
type LoggingPublisher struct {
	log *slog.Logger
}

func NewLoggingPublisher(log *slog.Logger) *LoggingPublisher {
	return &LoggingPublisher{log: log}
}

func (p *LoggingPublisher) Publish(ctx context.Context, event domain.Event) error {
	_ = ctx
	p.log.Info("core event",
		"eventId", event.EventID,
		"sessionId", event.SessionID,
		"type", event.Type,
		"timestamp", event.Timestamp.UTC().Format("2006-01-02T15:04:05.000Z"),
		"source", event.Source,
		"payload", event.Payload,
	)
	return nil
}
