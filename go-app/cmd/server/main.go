package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"benchapp/internal/httpapi"
	"benchapp/internal/platform"
	"benchapp/internal/store"
)

func main() {
	cfg, err := platform.LoadConfig()
	// log startup/error selalu tertulis: logger terpisah pada level info
	startup := platform.NewLogger("text", slog.LevelInfo)
	if err != nil {
		startup.Error("konfigurasi tidak valid: " + err.Error())
		os.Exit(2)
	}
	if cfg.LogFormat == "json" {
		startup = platform.NewLogger("json", slog.LevelInfo)
	}
	startup.WithFields(map[string]any{
		"port": cfg.Port, "log_mode": cfg.LogMode, "log_format": cfg.LogFormat, "db_pool": cfg.DBPool,
		"gomaxprocs": runtime.GOMAXPROCS(0), "go": runtime.Version(), "pprof": cfg.Profile,
	}).Info("server starting")

	db, err := platform.OpenDB(cfg)
	if err != nil {
		startup.Error("gagal membuka database: " + err.Error())
		os.Exit(1)
	}

	log := platform.NewLogger(cfg.LogFormat, platform.RequestLogLevel(cfg.LogMode))
	repo := store.New(db)
	srv := &http.Server{
		Addr:              ":" + cfg.Port,
		Handler:           httpapi.NewRouter(&httpapi.API{Users: repo, Orders: repo}, log),
		ReadHeaderTimeout: 10 * time.Second,
	}
	admin := &http.Server{
		Addr:              ":" + cfg.AdminPort,
		Handler:           platform.NewAdminHandler(db, cfg, cfg.Profile),
		ReadHeaderTimeout: 10 * time.Second,
	}
	go func() {
		if err := admin.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			startup.Error("admin server: " + err.Error())
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = srv.Shutdown(ctx)
		_ = admin.Shutdown(ctx)
	}()

	startup.Info("listening on :" + cfg.Port)
	if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		startup.Error("server berhenti: " + err.Error())
		os.Exit(1)
	}
}
