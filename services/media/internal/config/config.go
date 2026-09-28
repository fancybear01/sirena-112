package config

import (
	"fmt"
	"net/url"
	"os"
	"strconv"
	"strings"
)

// Config holds Media Gateway runtime settings from the environment.
type Config struct {
	HTTPAddr  string
	Mode      string
	AIBaseURL string

	ARIBaseURL  string
	ARIUsername string
	ARIPassword string
	ARIApp      string

	RTPListenAddr string
	RTPPort       int
	RTPPortEnd    int
	RTPPublicHost string

	CoreBaseURL             string
	LogLevel                string
	RecordingDir            string
	RecordingMaxSeconds     int
	RecordingRetentionHours int

	DefaultSIPDestination string
}

// Load reads configuration from environment variables.
func Load() (*Config, error) {
	cfg := &Config{
		Mode:                  getEnv("MEDIA_MODE", "echo"),
		AIBaseURL:             strings.TrimRight(getEnv("AI_BASE_URL", "ws://127.0.0.1:8090"), "/"),
		HTTPAddr:              getEnv("MEDIA_HTTP_ADDR", ":8091"),
		ARIBaseURL:            strings.TrimRight(getEnv("ARI_BASE_URL", "http://127.0.0.1:8088/ari"), "/"),
		ARIUsername:           getEnv("ARI_USERNAME", ""),
		ARIPassword:           getEnv("ARI_PASSWORD", ""),
		ARIApp:                getEnv("ARI_APP", "sirena-media"),
		RTPListenAddr:         getEnv("RTP_LISTEN_ADDR", "0.0.0.0"),
		RTPPublicHost:         getEnv("RTP_PUBLIC_HOST", "host.docker.internal"),
		CoreBaseURL:           strings.TrimRight(getEnv("CORE_BASE_URL", ""), "/"),
		RecordingDir:          getEnv("MEDIA_RECORDINGS_DIR", ""),
		LogLevel:              getEnv("LOG_LEVEL", "info"),
		DefaultSIPDestination: getEnv("DEFAULT_SIP_DESTINATION", "PJSIP/1001"),
	}

	port, err := strconv.Atoi(getEnv("RTP_PORT", "18000"))
	if err != nil {
		return nil, fmt.Errorf("RTP_PORT: %w", err)
	}
	cfg.RTPPort = port
	cfg.RTPPortEnd, err = strconv.Atoi(getEnv("RTP_PORT_END", strconv.Itoa(port)))
	if err != nil {
		return nil, fmt.Errorf("RTP_PORT_END: %w", err)
	}
	cfg.RecordingMaxSeconds, err = strconv.Atoi(getEnv("MEDIA_RECORDING_MAX_SECONDS", "900"))
	if err != nil {
		return nil, fmt.Errorf("MEDIA_RECORDING_MAX_SECONDS: %w", err)
	}
	cfg.RecordingRetentionHours, err = strconv.Atoi(getEnv("MEDIA_RECORDING_RETENTION_HOURS", "168"))
	if err != nil {
		return nil, fmt.Errorf("MEDIA_RECORDING_RETENTION_HOURS: %w", err)
	}

	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return cfg, nil
}

// Validate checks required settings. Secrets are never included in the error text.
func (c *Config) Validate() error {
	if c.RecordingDir != "" {
		if c.Mode != "ai" || c.CoreBaseURL == "" || len(os.Getenv("CORE_MEDIA_SERVICE_TOKEN")) < 32 || os.Getenv("CORE_AUTH_ENABLED") != "true" {
			return fmt.Errorf("recording requires MEDIA_MODE=ai, CORE_BASE_URL, CORE_MEDIA_SERVICE_TOKEN of at least 32 characters and CORE_AUTH_ENABLED=true")
		}
		if c.RecordingMaxSeconds < 1 || c.RecordingMaxSeconds > 3600 || c.RecordingRetentionHours < 1 || c.RecordingRetentionHours > 24*365 {
			return fmt.Errorf("recording duration/retention limits out of range")
		}
	}
	if c.Mode != "" && c.Mode != "echo" && c.Mode != "ai" {
		return fmt.Errorf("MEDIA_MODE must be echo or ai")
	}
	if c.Mode == "ai" {
		u, err := url.Parse(c.AIBaseURL)
		if err != nil || u.Host == "" || (u.Scheme != "ws" && u.Scheme != "wss") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return fmt.Errorf("AI_BASE_URL must be a ws(s) URL without credentials or query")
		}
	}
	if c.CoreBaseURL != "" {
		u, err := url.Parse(c.CoreBaseURL)
		if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
			return fmt.Errorf("CORE_BASE_URL must be an HTTP(S) base URL")
		}
	}
	if c.HTTPAddr == "" {
		return fmt.Errorf("MEDIA_HTTP_ADDR is required")
	}
	u, err := url.Parse(c.ARIBaseURL)
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("ARI_BASE_URL must be an HTTP(S) URL without credentials, query or fragment")
	}
	if c.ARIUsername == "" {
		return fmt.Errorf("ARI_USERNAME is required")
	}
	if c.ARIPassword == "" {
		return fmt.Errorf("ARI_PASSWORD is required")
	}
	if c.RTPPort <= 0 || c.RTPPort > 65535 {
		return fmt.Errorf("RTP_PORT must be between 1 and 65535")
	}
	if c.RTPPortEnd < c.RTPPort || c.RTPPortEnd > 65535 {
		return fmt.Errorf("RTP_PORT_END must be between RTP_PORT and 65535")
	}
	if c.RTPPublicHost == "" {
		return fmt.Errorf("RTP_PUBLIC_HOST is required")
	}
	return nil
}

func getEnv(key, defaultValue string) string {
	if value, ok := os.LookupEnv(key); ok {
		return value
	}
	return defaultValue
}
