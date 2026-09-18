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
  "github.com/fancybear01/sirena-112/services/media/internal/application/call"
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

  echoFactory := &rtp.Factory{Log: log}
  ariClient := ari.NewClient(ari.Config{
    BaseURL:       cfg.ARIBaseURL,
    Username:      cfg.ARIUsername,
    Password:      cfg.ARIPassword,
    App:           cfg.ARIApp,
    RTPPublicHost: cfg.RTPPublicHost,
    RTPListenHost: cfg.RTPListenAddr,
    RTPPort:       cfg.RTPPort,
    EchoFactory:   echoFactory,
    Log:           log,
  })
  publisher := coreadapter.NewLoggingPublisher(log)
  calls := call.NewService(ariClient, publisher, log)

  ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
  defer cancel()

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
  _ = srv.Shutdown(shutdownCtx)
  log.Info("media gateway stopped")
}
