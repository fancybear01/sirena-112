package voicefixture

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/fancybear01/sirena-112/services/media/internal/adapters/ai"
	"github.com/gorilla/websocket"
)

// Exercise the production WS client. The fake stays silent until input.flush,
// then interleaves JSON and PCM exactly like services/ai/app/voice/stream.py.
func TestFakeAITwoTurns(t *testing.T) {
	pcm := fixture(t, 1, "pcm")
	serverDone := make(chan struct{})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer close(serverDone)
		conn, err := (&websocket.Upgrader{}).Upgrade(w, r, nil)
		if err != nil {
			t.Error(err)
			return
		}
		defer conn.Close()
		conn.SetReadDeadline(time.Now().Add(3 * time.Second))
		k, b, err := conn.ReadMessage()
		var start map[string]any
		json.Unmarshal(b, &start)
		if err != nil || k != websocket.TextMessage || start["type"] != "stream.start" {
			t.Error("missing start")
			return
		}
		for turn := 0; turn < 2; turn++ {
			for i := 0; i < 3; i++ {
				k, b, err := conn.ReadMessage()
				if err != nil || k != websocket.BinaryMessage || !bytes.Equal(b, pcm) {
					t.Error("bad input PCM/order")
					return
				}
			}
			_, b, err = conn.ReadMessage()
			if err != nil || !bytes.Contains(b, []byte("input.flush")) {
				t.Error("missing flush")
				return
			}
			conn.WriteJSON(map[string]any{"type": "transcript.final", "simulated": true})
			conn.WriteJSON(map[string]any{"type": "response.started"})
			conn.WriteMessage(websocket.BinaryMessage, pcm)
			conn.WriteJSON(map[string]any{"type": "response.completed"})
			conn.WriteJSON(map[string]any{"type": "caller.state_changed", "hangUp": false})
		}
		_, b, err = conn.ReadMessage()
		if err != nil || !bytes.Contains(b, []byte("stream.stop")) {
			t.Error("missing stop")
		}
	}))
	defer srv.Close()
	output := make(chan string, 16)
	client, err := ai.Dial(context.Background(), ai.Config{BaseURL: "ws" + strings.TrimPrefix(srv.URL, "http")}, "session", "ai",
		func(b []byte) error {
			if !bytes.Equal(b, pcm) {
				t.Error("response PCM changed")
			}
			output <- "pcm"
			return nil
		},
		func(e map[string]any) error { output <- e["type"].(string); return nil }, func(err error) { output <- "error" })
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	for turn := 0; turn < 2; turn++ {
		for i := 0; i < 3; i++ {
			if err := client.SendPCM(pcm); err != nil {
				t.Fatal(err)
			}
		}
		if err := client.Control("input.flush"); err != nil {
			t.Fatal(err)
		}
		for _, want := range []string{"transcript.final", "response.started", "pcm", "response.completed", "caller.state_changed"} {
			select {
			case got := <-output:
				if got != want {
					t.Fatalf("want %s got %s", want, got)
				}
			case <-time.After(time.Second):
				t.Fatal("response timeout")
			}
		}
	}
	client.Close()
	select {
	case <-client.Done():
	case <-time.After(time.Second):
		t.Fatal("client leak")
	}
	select {
	case <-serverDone:
	case <-time.After(time.Second):
		t.Fatal("server leak")
	}
}
