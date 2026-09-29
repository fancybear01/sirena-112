package main

import (
	"context"
	"errors"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/ari"
	"github.com/fancybear01/sirena-112/services/media/internal/adapters/asterisk/rtp"
	coreadapter "github.com/fancybear01/sirena-112/services/media/internal/adapters/core"
	"github.com/fancybear01/sirena-112/services/media/internal/adapters/recording"
	"github.com/fancybear01/sirena-112/services/media/internal/application/call"
	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"github.com/fancybear01/sirena-112/services/media/internal/config"
	httpapi "github.com/fancybear01/sirena-112/services/media/internal/interfaces/http"
	"github.com/fancybear01/sirena-112/services/media/internal/platform/logger"
)

func main() {
	cfg, err := config.Load()
	if err != nil {
		panic(err)
	}
	log := logger.New(cfg.LogLevel)
	if cfg.RecordingDir != "" {
		if err := os.MkdirAll(cfg.RecordingDir, 0700); err != nil {
			panic(err)
		}
		if err := recording.RemoveIncomplete(cfg.RecordingDir); err != nil {
			panic(err)
		}
		if err := recording.Sweep(cfg.RecordingDir, time.Duration(cfg.RecordingRetentionHours)*time.Hour); err != nil {
			panic(err)
		}
	}

	var echoFactory ports.EchoFactory = &rtp.Factory{Log: log}
	if cfg.Mode == "ai" {
		echoFactory = &rtp.AIFactory{URL: cfg.AIBaseURL, Log: log, RecordingDir: cfg.RecordingDir, MaxRecording: time.Duration(cfg.RecordingMaxSeconds) * time.Second}
	}
	ariClient := ari.NewClient(ari.Config{
		BaseURL:       cfg.ARIBaseURL,
		Username:      cfg.ARIUsername,
		Password:      cfg.ARIPassword,
		App:           cfg.ARIApp,
		RTPPublicHost: cfg.RTPPublicHost,
		RTPListenHost: cfg.RTPListenAddr,
		RTPPort:       cfg.RTPPort,
		RTPPortEnd:    cfg.RTPPortEnd,
		EchoFactory:   echoFactory,
		Log:           log,
	})
	var publisher ports.CoreEventPublisher = coreadapter.NewLoggingPublisher(log)
	var httpPublisher *coreadapter.HTTPPublisher
	if cfg.CoreBaseURL != "" {
		httpPublisher = coreadapter.NewHTTPPublisher(cfg.CoreBaseURL, log)
		publisher = httpPublisher
	}
	calls := call.NewService(ariClient, publisher, log)
	calls.SetMaxCalls(cfg.MaxCalls)

	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	go calls.RunCleanup(ctx)
	if cfg.RecordingDir != "" {
		go func() {
			ticker := time.NewTicker(time.Hour)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					if err := recording.Sweep(cfg.RecordingDir, time.Duration(cfg.RecordingRetentionHours)*time.Hour); err != nil {
						log.Error("recording retention sweep failed", "err", err)
					}
				}
			}
		}()
	}

	if err := ariClient.Subscribe(ctx, calls.HandleARIEvent); err != nil {
		log.Error("ari subscribe failed", "err", err)
		os.Exit(1)
	}

	handler := httpapi.NewHandler(calls, ariClient, log)
	srv := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           handler.Routes(),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		log.Info("media gateway listening",
			"addr", cfg.HTTPAddr,
			"ari", cfg.ARIBaseURL,
			"app", cfg.ARIApp,
		)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Error("http server failed", "err", err)
			cancel()
		}
	}()

	<-ctx.Done()
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		log.Error("http shutdown failed", "err", err)
		_ = srv.Close()
	}
	cleanupCtx, cleanupCancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cleanupCancel()
	calls.Shutdown(cleanupCtx)
	if httpPublisher != nil {
		drainCtx, drainCancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer drainCancel()
		if err := httpPublisher.Close(drainCtx); err != nil {
			log.Error("Core publisher drain failed", "err", err)
		}
	}
	log.Info("media gateway stopped")
}
