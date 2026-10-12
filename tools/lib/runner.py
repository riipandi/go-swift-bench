"""Primitif run benchmark beban: infra, siapkan aplikasi, sampler, k6, statistik jendela steady, snapshot Postgres."""
import csv
import json
import math
import os
import re
import statistics
import subprocess
import threading
import time

from benchenv import (APP_CONTAINERS, APP_SERVICES, ROOT, container_info, db_sh, dc, load_env, log, psql, sh)

RESULTS = os.path.join(ROOT, "results")
SAMPLER_IMAGE = "bench-sampler:latest"
APP_URL = {"go": "http://go-app:8080", "swift": "http://swift-app:8080"}
ADMIN_URL = "http://go-app:6060/metrics/runtime"


# ------------------------------------------------------------------ lingkungan dan infra
def with_cpus(env, n, shift_others=False):
    """Salin env dengan batas CPU aplikasi n (GOMAXPROCS/event loop = n, pool = 8 x n)."""
    e = dict(env)
    e["APP_CPUS"] = str(n)
    e["APP_CPUSET"] = "0" if n == 1 else "0-%d" % (n - 1)
    e["DB_POOL_TOTAL"] = str(8 * n)
    e["EVENT_LOOPS"] = str(n)
    e["GOMAXPROCS_APP"] = str(n)
    return e


def thermal():
    r = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True)
    txt = (r.stdout + r.stderr).strip()
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", txt)
    limit = int(m.group(1)) if m else 100
    return {"cpu_speed_limit": limit, "throttled": limit < 100, "raw": txt.replace("\n", " | ")[:300]}


def wait_thermal_normal(max_wait=120):
    t0 = time.time()
    while thermal()["throttled"] and time.time() - t0 < max_wait:
        time.sleep(5)


def ensure_infra(env):
    """Postgres hidup, image sampler ada, k6 dan probe berjalan (di jaringan yang sama, dengan cpuset profil)."""
    dc(["up", "-d", "--wait", "postgres"], env=env)
    if subprocess.run(["docker", "image", "inspect", SAMPLER_IMAGE], capture_output=True).returncode != 0:
        dc(["build", "sampler"], env=env)
    dc(["up", "-d", "k6", "probe"], env=env)


def update_infra_cpusets(env):
    """Terapkan cpuset/CPU profil ke container yang berumur panjang tanpa recreate (docker update)."""
    for name, cpus, cpuset in (("bench-postgres", env["PG_CPUS"], env["PG_CPUSET"]),
                               ("bench-k6", env["K6_CPUS"], env["K6_CPUSET"]),
                               ("bench-probe", "1", env["SAMPLER_CPUSET"])):
        sh(["docker", "update", "--cpuset-cpus", cpuset, "--cpus", cpus, name], check=False)


def probe(args, timeout=90):
    r = sh(["docker", "exec", "bench-probe", "/sampler", "probe"] + args, timeout=timeout)
    return r.stdout.strip()


def stop_apps(env):
    for app in APP_SERVICES:
        dc(["stop", APP_SERVICES[app]], env=env, check=False)


def prepare_app(app, env, tag_env=None, timeout=60):
    """Satu aplikasi aktif; DB direset dari template; statistik Postgres di-reset; container di-restart sampai /healthz 200."""
    e = dict(env)
    if tag_env:
        e.update(tag_env)
    stop_apps(e)
    db_sh(["reset"], env=e)
    psql("bench", "SELECT pg_stat_statements_reset(); SELECT pg_stat_reset();")
    dc(["up", "-d", "--force-recreate", APP_SERVICES[app]], env=e)
    probe(["wait", "--url", APP_URL[app] + "/healthz", "--timeout", "%ds" % timeout], timeout=timeout + 10)
    time.sleep(1.0)


def target_args(app):
    ts = []
    for name, cname, proc in (("app", APP_CONTAINERS[app], True), ("pg", "bench-postgres", False), ("k6", "bench-k6", False)):
        info = container_info(cname)
        ts += ["--target", "%s:%s:%d%s" % (name, info["Id"], info["State"]["Pid"], "" if proc else ":noproc")]
    return ts


class Sampler:
    """Container sampler (pid=host, cgroupns=host) + pembanding silang 'docker stats'."""

    def __init__(self, env, app, run_dir):
        self.env, self.app, self.run_dir = env, app, run_dir
        self.name = "bench-sampler"
        self.docker_stats_thread = None
        self._stop = threading.Event()

    def start(self):
        os.makedirs(self.run_dir, exist_ok=True)
        rel = os.path.relpath(self.run_dir, RESULTS)
        sh(["docker", "rm", "-f", self.name], check=False)
        sh(["docker", "run", "-d", "--rm", "--name", self.name, "--pid", "host", "--cgroupns", "host",
            "--cpuset-cpus", self.env["SAMPLER_CPUSET"], "--memory", self.env["SAMPLER_MEM"], "-v", RESULTS + ":/results",
            SAMPLER_IMAGE, "sample", "--out", "/results/%s/sampler.csv" % rel] + target_args(self.app))
        self._stop.clear()
        self.docker_stats_thread = threading.Thread(target=self._docker_stats, daemon=True)
        self.docker_stats_thread.start()

    def _docker_stats(self):
        path = os.path.join(self.run_dir, "docker_stats.csv")
        names = [APP_CONTAINERS[self.app], "bench-postgres", "bench-k6"]
        with open(path, "w") as f:
            f.write("ts_ms,name,cpu_pct,mem_usage\n")
            while not self._stop.is_set():
                r = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}"] + names,
                                   capture_output=True, text=True)
                now = int(time.time() * 1000)
                for line in r.stdout.splitlines():
                    p = line.split("|")
                    if len(p) == 3:
                        f.write("%d,%s,%s,%s\n" % (now, p[0], p[1].rstrip("%"), p[2].split("/")[0].strip()))
                f.flush()
                self._stop.wait(1.0)

    def stop(self):
        self._stop.set()
        sh(["docker", "stop", "-t", "5", self.name], check=False)
        if self.docker_stats_thread:
            self.docker_stats_thread.join(timeout=10)


# ------------------------------------------------------------------ k6
def run_k6(env, app, run_dir, name, params, timeout=None):
    """Satu invokasi k6 (di container) -> file ringkasan --summary-export. Mengembalikan dict ringkasan."""
    rel = os.path.relpath(run_dir, RESULTS)
    out_rel = "/results/%s/k6_%s.json" % (rel, name)
    cmd = ["docker", "exec"]
    base = {"BASE_URL": APP_URL[app], "SEED": env.get("SEED", "20261013")}
    for k, v in dict(base, **params).items():
        cmd += ["-e", "%s=%s" % (k, v)]
    cmd += ["bench-k6", "k6", "run", "--quiet", "--no-color", "--summary-export", out_rel, "/loadtest/main.js"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode not in (0,):
        raise RuntimeError("k6 gagal (%d): %s" % (r.returncode, (r.stdout + r.stderr)[-800:]))
    return json.load(open(os.path.join(run_dir, "k6_%s.json" % name)))


def metric(summary, name):
    m = summary["metrics"].get(name)
    if m is None:
        raise KeyError("metrik %s tidak ada di ringkasan k6" % name)
    return m.get("values", m)


def k6_numbers(summary):
    """Angka steady dari ringkasan k6: jumlah request, error rate, latensi (ms), dropped, t0 (ms epoch VM)."""
    dur = metric(summary, "http_req_duration{phase:steady}")
    reqs = metric(summary, "http_reqs{phase:steady}")
    failed = metric(summary, "http_req_failed{phase:steady}")
    total = metric(summary, "http_reqs")
    dropped = summary["metrics"].get("dropped_iterations")
    err = failed.get("rate", failed.get("value", 0.0))
    return {
        "req_steady": int(reqs["count"]),
        "req_total": int(total["count"]),
        "err_rate": float(err),
        "lat_ms": {k: dur.get(k) for k in ("avg", "min", "med", "max", "p(90)", "p(95)", "p(99)", "p(99.9)")},
        "dropped": int(metric(summary, "dropped_iterations")["count"]) if dropped else 0,
        "t0_ms": int(metric(summary, "bench_test_start_ms").get("value", 0)),
    }


# ------------------------------------------------------------------ sampler -> statistik jendela
def load_sampler(run_dir):
    rows = {}
    path = os.path.join(run_dir, "sampler.csv")
    if not os.path.exists(path):
        return rows
    for r in csv.DictReader(open(path)):
        if r["ok"] != "1":
            continue
        rows.setdefault(r["target"], []).append({k: (int(v) if v not in ("", None) and k != "target" else v) for k, v in r.items()})
    return rows


def window(rows, lo_ms, hi_ms):
    return [r for r in rows if lo_ms <= r["ts_ms"] <= hi_ms]


def cpu_stats(rows, lo, hi):
    w = window(rows, lo, hi)
    if len(w) < 2:
        return None
    dt = (w[-1]["ts_ms"] - w[0]["ts_ms"]) / 1000.0
    d = lambda k: w[-1][k] - w[0][k]
    return {"cores": d("cpu_usage_us") / 1e6 / dt, "user_cores": d("cpu_user_us") / 1e6 / dt, "sys_cores": d("cpu_system_us") / 1e6 / dt,
            "throttled_ms": d("throttled_us") / 1000.0, "cpu_ms": d("cpu_usage_us") / 1000.0, "dt": dt}


def per_second_cores(rows, lo, hi):
    w = window(rows, lo, hi)
    out = []
    for a, b in zip(w, w[1:]):
        dt = (b["ts_ms"] - a["ts_ms"]) / 1000.0
        if dt > 0:
            out.append((b["cpu_usage_us"] - a["cpu_usage_us"]) / 1e6 / dt)
    return out


def app_resource_stats(samp, lo, hi):
    """Metrik resource aplikasi pada jendela steady."""
    app = samp.get("app", [])
    c = cpu_stats(app, lo, hi)
    w = window(app, lo, hi)
    if c is None or not w:
        return None
    dt = c["dt"]
    mb = lambda b: b / 1048576.0
    return {
        "cpu_cores": c["cores"], "cpu_user_cores": c["user_cores"], "cpu_sys_cores": c["sys_cores"], "cpu_ms": c["cpu_ms"],
        "throttled_ms": c["throttled_ms"],
        "mem_avg_mb": mb(statistics.mean(r["mem_current"] for r in w)),
        "mem_max_mb": mb(max(r["mem_current"] for r in w)),
        "mem_peak_mb": mb(w[-1]["mem_peak"]),
        "mem_anon_mb": mb(w[-1]["mem_anon"]), "mem_file_mb": mb(w[-1]["mem_file"]),
        "threads_max": max(r["threads"] for r in w), "fds_max": max(r["fds"] for r in w), "pids_max": max(r["pids"] for r in w),
        "ctx_vol_per_s": (w[-1]["vol_cs"] - w[0]["vol_cs"]) / dt, "ctx_nonvol_per_s": (w[-1]["nonvol_cs"] - w[0]["nonvol_cs"]) / dt,
        "net_rx_bps": (w[-1]["net_rx"] - w[0]["net_rx"]) / dt, "net_tx_bps": (w[-1]["net_tx"] - w[0]["net_tx"]) / dt,
        "io_r_bps": (w[-1]["io_rbytes"] - w[0]["io_rbytes"]) / dt, "io_w_bps": (w[-1]["io_wbytes"] - w[0]["io_wbytes"]) / dt,
    }


# ------------------------------------------------------------------ Postgres
PG_SNAPSHOT_SQL = """
SELECT json_build_object(
 'statements', (SELECT coalesce(json_agg(json_build_object('query', regexp_replace(s.query, '\\s+', ' ', 'g'), 'calls', s.calls,
      'total_exec_ms', s.total_exec_time, 'mean_exec_ms', s.mean_exec_time, 'rows', s.rows)), '[]'::json)
      FROM pg_stat_statements s JOIN pg_database d ON d.oid = s.dbid WHERE d.datname = 'bench' AND s.query NOT ILIKE '%pg_stat_%'),
 'database', (SELECT row_to_json(x) FROM (SELECT xact_commit, xact_rollback, blks_read, blks_hit, tup_returned, tup_fetched,
      tup_inserted, tup_updated, deadlocks, temp_files FROM pg_stat_database WHERE datname = 'bench') x),
 'activity', (SELECT coalesce(json_agg(row_to_json(a)), '[]'::json) FROM (SELECT state, wait_event_type, wait_event, count(*) AS n
      FROM pg_stat_activity WHERE datname = 'bench' GROUP BY 1, 2, 3) a));
"""


def pg_snapshot(path):
    out = psql("bench", PG_SNAPSHOT_SQL)
    with open(path, "w") as f:
        f.write(out + "\n")


def pg_calls_total():
    return int(psql("bench", "SELECT coalesce(sum(s.calls),0)::bigint FROM pg_stat_statements s JOIN pg_database d ON d.oid=s.dbid "
                             "WHERE d.datname='bench' AND s.query NOT ILIKE '%pg_stat_%';"))


def pg_connections():
    return int(psql("bench", "SELECT count(*) FROM pg_stat_activity WHERE datname='bench' AND backend_type='client backend' AND pid <> pg_backend_pid();"))


# ------------------------------------------------------------------ log dan runtime Go
def log_stats(app):
    r = subprocess.run(["docker", "logs", APP_CONTAINERS[app]], capture_output=True)
    data = r.stdout + r.stderr
    return {"lines": data.count(b"\n"), "bytes": len(data)}


def go_runtime():
    try:
        return json.loads(probe(["get", "--url", ADMIN_URL], timeout=20))
    except Exception:
        return None


# ------------------------------------------------------------------ satu titik ukur
def run_point(env, app, run_dir, label, mode, params, steady_s, ramp_s, slo_ms, k6_cpu_limit=0.8):
    """Menjalankan satu invokasi k6 dan menghitung metrik dari jendela steady. Mengembalikan dict titik."""
    calls0 = pg_calls_total()
    rt0 = go_runtime() if app == "go" else None
    th0 = thermal()
    p = dict(params, MODE=mode, SCENARIO=params["SCENARIO"])
    summary = run_k6(env, app, run_dir, label, p)
    time.sleep(1.2)  # biarkan sampler menulis baris terakhir
    th1 = thermal()
    rt1 = go_runtime() if app == "go" else None
    calls1 = pg_calls_total()
    kn = k6_numbers(summary)
    t0 = kn["t0_ms"]
    if mode == "vus":
        lo, hi = t0 + ramp_s * 1000 + 700, t0 + (ramp_s + steady_s) * 1000 - 300
    else:
        lo, hi = t0 + 1000, t0 + steady_s * 1000 - 300
    samp = load_sampler(run_dir)
    res = app_resource_stats(samp, lo, hi) or {}
    pgc = cpu_stats(samp.get("pg", []), lo, hi) or {}
    k6c = cpu_stats(samp.get("k6", []), lo, hi) or {}
    pg_sec = per_second_cores(samp.get("pg", []), lo, hi)
    steady_dt = (hi - lo) / 1000.0
    rps = kn["req_steady"] / float(steady_s)
    flags = []
    k6_util = (k6c.get("cores", 0.0) / float(env["K6_CPUS"])) if k6c else 0.0
    if k6_util > k6_cpu_limit:
        flags.append("k6_bound")
    if th0["throttled"] or th1["throttled"]:
        flags.append("thermal_throttled")
    if not res:
        flags.append("no_cgroup_data")
    pg_util = (pgc.get("cores", 0.0) / float(env["PG_CPUS"])) if pgc else 0.0
    if pg_util >= 0.9:
        flags.append("db_bound")
    point = {
        "label": label, "mode": mode, "params": {k: v for k, v in params.items() if k in ("VUS", "RATE", "DURATION_S")},
        "steady_s": steady_s, "rps": rps, "req_steady": kn["req_steady"], "req_total": kn["req_total"],
        "err_rate": kn["err_rate"], "dropped": kn["dropped"], "lat_ms": kn["lat_ms"],
        "p99_ok": kn["lat_ms"]["p(99)"] is not None and kn["lat_ms"]["p(99)"] < slo_ms,
        "res": res,
        "cpu_ms_per_req": (res["cpu_ms"] / max(1, kn["req_steady"])) if res else None,
        "rps_per_core": (rps / res["cpu_cores"]) if res and res["cpu_cores"] > 0 else None,
        "rps_per_gb_peak": (rps / (res["mem_peak_mb"] / 1024.0)) if res and res["mem_peak_mb"] > 0 else None,
        "pg_cores": pgc.get("cores"), "pg_util": pg_util, "pg_cores_max_1s": max(pg_sec) if pg_sec else None,
        "k6_cores": k6c.get("cores"), "k6_util": k6_util,
        "queries_total": calls1 - calls0, "queries_per_req": (calls1 - calls0) / max(1, kn["req_total"]),
        "pg_connections": pg_connections(),
        "thermal_before": th0["cpu_speed_limit"], "thermal_after": th1["cpu_speed_limit"],
        "flags": flags, "valid": not ({"k6_bound", "thermal_throttled"} & set(flags)),
    }
    if rt0 and rt1:
        point["go_runtime"] = {"gc_cycles_delta": rt1.get("/gc/cycles/total:gc-cycles", 0) - rt0.get("/gc/cycles/total:gc-cycles", 0),
                               "gc_pause_count_delta": rt1.get("/gc/pauses:seconds/count", 0) - rt0.get("/gc/pauses:seconds/count", 0),
                               "gc_pause_approx_sum_s_delta": rt1.get("/gc/pauses:seconds/approx_sum_s", 0) - rt0.get("/gc/pauses:seconds/approx_sum_s", 0),
                               "goroutines": rt1.get("/sched/goroutines:goroutines"),
                               "heap_objects_mb": rt1.get("/memory/classes/heap/objects:bytes", 0) / 1048576.0}
    return point


def saturation_of(points, slo_ms, max_err=0.001):
    """RPS tertinggi dengan error < 0,1% dan p99 < SLO. Tanpa titik lolos: titik ber-VU terendah (ditandai fallback)."""
    ok = [p for p in points if p["err_rate"] < max_err and p["p99_ok"] and p["valid"]]
    if ok:
        best = max(ok, key=lambda p: p["rps"])
        return best["rps"], False
    if points:
        return min(points, key=lambda p: int(p["params"].get("VUS", 0) or 0))["rps"], True
    return 0.0, True
