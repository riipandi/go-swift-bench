package platform

import (
	"encoding/json"
	"net/http"
	"net/http/pprof"
	"runtime"
	"runtime/metrics"
	"time"

	"gorm.io/gorm"
)

var adminSamples = []metrics.Sample{
	{Name: "/sched/goroutines:goroutines"},
	{Name: "/gc/cycles/total:gc-cycles"},
	{Name: "/gc/heap/allocs:bytes"},
	{Name: "/memory/classes/heap/objects:bytes"},
	{Name: "/memory/classes/total:bytes"},
	{Name: "/gc/pauses:seconds"},
}

// NewAdminHandler mengekspos runtime/metrics (+ konfigurasi runtime dan statistik pool) di port admin.
// pprof hanya terpasang bila profile == true (PROFILE=1); tidak pernah aktif saat run pengukuran.
func NewAdminHandler(db *gorm.DB, cfg Config, profile bool) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/metrics/runtime", func(w http.ResponseWriter, r *http.Request) {
		samples := make([]metrics.Sample, len(adminSamples))
		copy(samples, adminSamples)
		metrics.Read(samples)
		out := map[string]any{
			"gomaxprocs":    runtime.GOMAXPROCS(0),
			"num_cpu":       runtime.NumCPU(),
			"version":       runtime.Version(),
			"log_mode":      cfg.LogMode,
			"log_format":    cfg.LogFormat,
			"db_pool_total": cfg.DBPool,
			"now":           time.Now().UTC().Format(time.RFC3339),
		}
		for _, s := range samples {
			switch s.Value.Kind() {
			case metrics.KindUint64:
				out[s.Name] = s.Value.Uint64()
			case metrics.KindFloat64:
				out[s.Name] = s.Value.Float64()
			case metrics.KindFloat64Histogram:
				h := s.Value.Float64Histogram()
				var total uint64
				var sum float64
				for i, c := range h.Counts {
					total += c
					sum += float64(c) * h.Buckets[i]
				}
				out[s.Name+"/count"] = total
				out[s.Name+"/approx_sum_s"] = sum
			}
		}
		if db != nil {
			if sqlDB, err := db.DB(); err == nil {
				st := sqlDB.Stats()
				out["db_max_open"] = st.MaxOpenConnections
				out["db_open"] = st.OpenConnections
				out["db_in_use"] = st.InUse
				out["db_idle"] = st.Idle
				out["db_wait_count"] = st.WaitCount
			}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(out)
	})
	if profile {
		mux.HandleFunc("/debug/pprof/", pprof.Index)
		mux.HandleFunc("/debug/pprof/cmdline", pprof.Cmdline)
		mux.HandleFunc("/debug/pprof/profile", pprof.Profile)
		mux.HandleFunc("/debug/pprof/symbol", pprof.Symbol)
		mux.HandleFunc("/debug/pprof/trace", pprof.Trace)
	}
	return mux
}
