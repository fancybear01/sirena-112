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

func TestInternalRoutesRequireServiceTokenWhenConfigured(t *testing.T) {
	t.Setenv("CORE_MEDIA_SERVICE_TOKEN", "test-internal-token")
	h := (&Handler{log: slog.Default()}).Routes()
	request := httptest.NewRequest(http.MethodGet, "/internal/unknown", nil)
	response := httptest.NewRecorder()
	h.ServeHTTP(response, request)
	if response.Code != http.StatusUnauthorized {
		t.Fatalf("anonymous status = %d", response.Code)
	}
	request = httptest.NewRequest(http.MethodGet, "/internal/unknown", nil)
	request.Header.Set("Authorization", "Bearer test-internal-token")
	response = httptest.NewRecorder()
	h.ServeHTTP(response, request)
	if response.Code != http.StatusNotFound {
		t.Fatalf("authenticated status = %d", response.Code)
	}
}
