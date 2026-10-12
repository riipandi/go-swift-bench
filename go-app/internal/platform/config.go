// Package platform: konfigurasi lingkungan, logging LogLayer, pool DB, dan server admin.
package platform

import (
	"fmt"
	"os"
	"strconv"
)

type Config struct {
	Port      string
	AdminPort string
	DBHost    string
	DBPort    string
	DBUser    string
	DBPass    string
	DBName    string
	DBPool    int    // total koneksi (SetMaxOpenConns = SetMaxIdleConns)
	LogMode   string // quiet | access
	LogFormat string // text | json
	Profile   bool   // PROFILE=1 mengaktifkan net/http/pprof di port admin
}

func getenv(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func LoadConfig() (Config, error) {
	pool, err := strconv.Atoi(getenv("DB_POOL", "16"))
	if err != nil || pool < 1 {
		return Config{}, fmt.Errorf("DB_POOL tidak valid")
	}
	c := Config{
		Port:      getenv("PORT", "8080"),
		AdminPort: getenv("ADMIN_PORT", "6060"),
		DBHost:    getenv("DB_HOST", "localhost"),
		DBPort:    getenv("DB_PORT", "54322"),
		DBUser:    getenv("DB_USER", "bench"),
		DBPass:    getenv("DB_PASSWORD", "bench"),
		DBName:    getenv("DB_NAME", "bench"),
		DBPool:    pool,
		LogMode:   getenv("LOG_MODE", "quiet"),
		LogFormat: getenv("LOG_FORMAT", "text"),
		Profile:   getenv("PROFILE", "0") == "1",
	}
	if c.LogMode != "quiet" && c.LogMode != "access" {
		return Config{}, fmt.Errorf("LOG_MODE harus quiet atau access")
	}
	if c.LogFormat != "text" && c.LogFormat != "json" {
		return Config{}, fmt.Errorf("LOG_FORMAT harus text atau json")
	}
	return c, nil
}
