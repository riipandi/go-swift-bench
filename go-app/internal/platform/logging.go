package platform

import (
	"log/slog"
	"os"

	llslog "go.loglayer.dev/transports/slog/v3"
	"go.loglayer.dev/v3"
)

// NewLogger membungkus slog dengan LogLayer (transport slog). Keluaran ke stdout.
func NewLogger(format string, level slog.Level) *loglayer.LogLayer {
	lv := new(slog.LevelVar)
	lv.Set(level)
	opts := &slog.HandlerOptions{Level: lv}
	var h slog.Handler
	if format == "json" {
		h = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		h = slog.NewTextHandler(os.Stdout, opts)
	}
	return loglayer.New(loglayer.Config{
		Transport: llslog.New(llslog.Config{Logger: slog.New(h)}),
	})
}

// RequestLogLevel: quiet = error (baris akses tersaring), access = info (satu baris per request).
func RequestLogLevel(mode string) slog.Level {
	if mode == "access" {
		return slog.LevelInfo
	}
	return slog.LevelError
}
