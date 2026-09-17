package config

import (
	"os"
)

type Config struct {
	AsteriskHost string
	AsteriskPort string
}

func LoadConfig() *Config {
	return &Config{
		AsteriskHost: getEnv("ASTERISK_HOST", "localhost"),
		AsteriskPort: getEnv("ASTERISK_PORT", "8088"),
	}
}

func getEnv(key, defaultValue string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return defaultValue
}
