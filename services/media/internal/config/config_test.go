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
