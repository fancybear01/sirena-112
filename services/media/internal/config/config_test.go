package config_test

import (
	"strings"
	"testing"

	"github.com/fancybear01/sirena-112/services/media/internal/config"
)

func TestValidateRequiresARICredentials(t *testing.T) {
	cfg := &config.Config{
		HTTPAddr:      ":8091",
		ARIBaseURL:    "http://127.0.0.1:8088/ari",
		RTPPort:       18000,
		RTPPortEnd:    18000,
		RTPPublicHost: "127.0.0.1",
	}
	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected error when ARI credentials missing")
	}
	if strings.Contains(err.Error(), "secret") {
		t.Fatalf("error must not contain secret values: %v", err)
	}

	cfg.ARIUsername = "media"
	cfg.ARIPassword = "secret"
	if err := cfg.Validate(); err != nil {
		t.Fatal(err)
	}
}

func TestValidateARIURL(t *testing.T) {
	for _, base := range []string{"localhost:8088", "ftp://localhost/ari", "http://user:secret@localhost/ari", "http://localhost/ari?api_key=secret"} {
		cfg := &config.Config{HTTPAddr: ":8091", ARIBaseURL: base, ARIUsername: "media", ARIPassword: "secret", RTPPort: 18000, RTPPortEnd: 18000, RTPPublicHost: "localhost"}
		err := cfg.Validate()
		if err == nil || strings.Contains(err.Error(), "secret") {
			t.Fatalf("URL validation leaked credentials or accepted invalid URL: %v", err)
		}
	}
}

func TestPortRangeConfiguration(t *testing.T) {
	t.Setenv("ARI_USERNAME", "media")
	t.Setenv("ARI_PASSWORD", "secret")
	t.Setenv("RTP_PORT", "18000")
	t.Setenv("RTP_PORT_END", "18099")
	cfg, err := config.Load()
	if err != nil || cfg.RTPPortEnd != 18099 {
		t.Fatalf("range: %+v %v", cfg, err)
	}
	for _, end := range []string{"17999", "65536", "-1", "0", "bad"} {
		t.Setenv("RTP_PORT_END", end)
		if _, err := config.Load(); err == nil {
			t.Errorf("accepted RTP_PORT_END=%s", end)
		}
	}
}
