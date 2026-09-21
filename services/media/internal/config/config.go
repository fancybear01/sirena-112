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
	HTTPAddr string

	ARIBaseURL  string
	ARIUsername string
	ARIPassword string
	ARIApp      string

	RTPListenAddr string
	RTPPort       int
	RTPPortEnd    int
	RTPPublicHost string

	CoreBaseURL string
	LogLevel    string

	DefaultSIPDestination string
}

// Load reads configuration from environment variables.
func Load() (*Config, error) {
	cfg := &Config{
		HTTPAddr:              getEnv("MEDIA_HTTP_ADDR", ":8091"),
		ARIBaseURL:            strings.TrimRight(getEnv("ARI_BASE_URL", "http://127.0.0.1:8088/ari"), "/"),
		ARIUsername:           getEnv("ARI_USERNAME", ""),
		ARIPassword:           getEnv("ARI_PASSWORD", ""),
		ARIApp:                getEnv("ARI_APP", "sirena-media"),
		RTPListenAddr:         getEnv("RTP_LISTEN_ADDR", "0.0.0.0"),
		RTPPublicHost:         getEnv("RTP_PUBLIC_HOST", "host.docker.internal"),
		CoreBaseURL:           strings.TrimRight(getEnv("CORE_BASE_URL", ""), "/"),
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

	if err := cfg.Validate(); err != nil {
		return nil, err
	}
	return cfg, nil
}

// Validate checks required settings. Secrets are never included in the error text.
func (c *Config) Validate() error {
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
