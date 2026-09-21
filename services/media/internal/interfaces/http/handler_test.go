package httpapi

import (
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/domain"
)

func TestCapacityExhaustedIsUnavailable(t *testing.T) {
	h := &Handler{log: slog.Default()}
	w := httptest.NewRecorder()
	h.mapError(w, domain.ErrCapacityExhausted)
	if w.Code != http.StatusServiceUnavailable || !strings.Contains(w.Body.String(), `"capacity_exhausted"`) {
		t.Fatalf("response: %d %s", w.Code, w.Body.String())
	}
}
