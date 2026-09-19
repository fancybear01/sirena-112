package ari

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/application/ports"
	"log/slog"
	"os"
)

type noopEcho struct{}

func (noopEcho) Start(ctx context.Context) error { return nil }
func (noopEcho) Stop(ctx context.Context) error  { return nil }
func (noopEcho) Stats() ports.RTPStats           { return ports.RTPStats{} }

type noopFactory struct{}

func (noopFactory) Create(listenHost string, listenPort int) (ports.EchoSession, int, error) {
	return noopEcho{}, listenPort, nil
}

func TestReadyAgainstMockARI(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		user, pass, ok := r.BasicAuth()
		if !ok || user != "media" || pass != "secret" {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		if r.URL.Path != "/ari/asterisk/info" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"system": map[string]string{"version": "20"}})
	}))
	defer srv.Close()

	client := NewClient(Config{
		BaseURL:       srv.URL + "/ari",
		Username:      "media",
		Password:      "secret",
		App:           "sirena-media",
		RTPPublicHost: "127.0.0.1",
		RTPListenHost: "127.0.0.1",
		RTPPort:       0,
		EchoFactory:   noopFactory{},
		Log:           slog.New(slog.NewTextHandler(os.Stderr, nil)),
	})
	if err := client.Ready(context.Background()); err == nil {
		t.Fatal("ready without event stream")
	}
	client.connected.Store(true)
	if err := client.Ready(context.Background()); err != nil {
		t.Fatal(err)
	}
}
