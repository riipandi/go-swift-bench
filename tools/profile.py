#!/usr/bin/env python3
"""make profile: profil CPU/alokasi pada S8 (atau SCENARIO) dengan aplikasi NATIVE (konfigurasi release) dan Postgres di Docker.

k6 (container) menembak lewat host.docker.internal pada laju tetap 50% RPS saturasi (saturasi implementasi yang lebih lambat dari
run beban terakhir; atau RATE=...). Profiler hanya aktif di run ini (Go: PROFILE=1; Swift: sample/xctrace) - tidak pernah saat pengukuran.
Hasil: results/profiles/<app>/<skenario>/ ; 10 fungsi teratas di top10.json (penjelasan, bukan perbandingan).
"""
import gzip
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from benchenv import ROOT, db_sh, dc, load_env, log, psql, sh, wait_http  # noqa: E402
from flame import parse_traces, to_svg  # noqa: E402
from runner import RESULTS, ensure_infra, run_k6, stop_apps, update_infra_cpusets  # noqa: E402

PORTS = {"go": 8080, "swift": 8081}


def find_rate(scenario, env):
    if os.environ.get("RATE"):
        return int(os.environ["RATE"]), "RATE dari environment"
    base = os.path.join(RESULTS, "raw")
    cands = sorted([d for d in os.listdir(base) if d.endswith(("-bench", "-bench-smoke"))], reverse=True) if os.path.isdir(base) else []
    cands.sort(key=lambda d: ("smoke" in d, ""))  # run penuh lebih diutamakan daripada smoke
    for d in sorted(cands, key=lambda d: (("smoke" in d), -os.path.getmtime(os.path.join(base, d)))):
        p = os.path.join(base, d, "saturation.json")
        if os.path.exists(p):
            s = json.load(open(p)).get(scenario)
            if s and s.get("slower"):
                return max(1, int(s["slower"] * 0.5)), "50%% saturasi (yang lebih lambat) dari %s%s" % (d, " [SMOKE]" if "smoke" in d else "")
    return 500, "peringatan: belum ada data saturasi; memakai 500 RPS (jalankan make bench-core dulu agar sesuai spesifikasi)"


def start_native(app, env, out_dir):
    e = dict(os.environ)
    e.update(DB_HOST="localhost", DB_PORT="54322", DB_USER="bench", DB_PASSWORD="bench", DB_NAME="bench", LOG_MODE="quiet",
             DB_POOL=env["DB_POOL_TOTAL"], PORT=str(PORTS[app]))
    if app == "go":
        binp = os.path.join(ROOT, "bin", "go-server-release")
        os.makedirs(os.path.dirname(binp), exist_ok=True)
        subprocess.run(["go", "build", "-trimpath", "-ldflags=-s -w", "-o", binp, "./cmd/server"], cwd=os.path.join(ROOT, "go-app"), check=True)
        e.update(PROFILE="1", GOMAXPROCS=env["GOMAXPROCS_APP"], ADMIN_PORT="6060")
    else:
        subprocess.run(["swift", "build", "-c", "release", "--product", "App"], cwd=os.path.join(ROOT, "swift-app"), check=True,
                       capture_output=True)
        binp = subprocess.run(["swift", "build", "-c", "release", "--show-bin-path"], cwd=os.path.join(ROOT, "swift-app"),
                              capture_output=True, text=True).stdout.strip().splitlines()[-1] + "/App"
        e.update(EVENT_LOOPS=env["EVENT_LOOPS"])
    logf = open(os.path.join(out_dir, "app.log"), "w")
    proc = subprocess.Popen([binp], env=e, stdout=logf, stderr=subprocess.STDOUT)
    wait_http(PORTS[app], timeout=60)
    return proc, binp


def fetch(url, path, timeout):
    with urllib.request.urlopen(url, timeout=timeout) as r, open(path, "wb") as f:
        f.write(r.read())


def top_go(pb, n=10):
    r = subprocess.run(["go", "tool", "pprof", "-top", "-nodecount=%d" % (n + 5), pb], capture_output=True, text=True)
    rows = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s*([\d.]+)(ms|s|us|ns|MB|kB|B)?\s+([\d.]+)%\s+([\d.]+)%\s+([\d.]+)(ms|s|us|ns|MB|kB|B)?\s+([\d.]+)%\s+(.*)$", line)
        if m:
            rows.append({"flat": m.group(1) + (m.group(2) or ""), "flat_pct": float(m.group(3)), "cum": m.group(5) + (m.group(6) or ""),
                         "cum_pct": float(m.group(7)), "name": m.group(8).strip()})
    return rows[:n], r.stdout.split("\n\n")[0][:600]


def top_sample(path, n=10):
    """Bagian 'Sort by top of stack' dari keluaran macOS sample."""
    txt = open(path, errors="replace").read()
    i = txt.find("Sort by top of stack")
    rows = []
    if i >= 0:
        for line in txt[i:].splitlines()[1:]:
            m = re.match(r"\s+(\S.*?)\s{2,}\(in ([^)]+)\)\s+(\d+)\s*$", line)
            if m:
                rows.append({"name": m.group(1), "image": m.group(2), "samples": int(m.group(3))})
            if len(rows) >= n:
                break
    total = sum(r["samples"] for r in rows) or 1
    return rows


def main():
    app = os.environ.get("APP", "go")
    if app not in ("go", "swift"):
        raise SystemExit("profile: APP harus go atau swift")
    scenario = os.environ.get("SCENARIO", "s8").lower()
    if "," in scenario or scenario in ("core", "all"):
        scenario = "s8"
    duration = int(os.environ.get("DURATION", "45"))
    env = load_env()
    out_dir = os.path.join(RESULTS, "profiles", app, scenario)
    os.makedirs(out_dir, exist_ok=True)
    rate, rate_note = find_rate(scenario, env)
    log("profile %s %s | %ds | laju tetap %d RPS (%s)" % (app, scenario, duration, rate, rate_note))
    log("Aplikasi NATIVE (release) + Postgres Docker; profiler aktif hanya di run ini. Estimasi: ~%d detik + build" % (duration + 40))

    stop_apps(env)
    ensure_infra(env)
    update_infra_cpusets(env)
    db_sh(["reset"], env=env)
    psql("bench", "SELECT pg_stat_statements_reset();")
    proc, binp = start_native(app, env, out_dir)
    try:
        pid = proc.pid
        base = "http://host.docker.internal:%d" % PORTS[app]
        e2 = dict(env)
        # warm-up (tidak dihitung)
        sh_env = {"SCENARIO": scenario, "MODE": "warmup", "VUS": 32, "DURATION_S": 10, "BASE_URL": base}
        os.makedirs(os.path.join(out_dir, "k6"), exist_ok=True)
        _run_k6_host(env, out_dir, "warmup", sh_env)
        k6_params = {"SCENARIO": scenario, "MODE": "rate", "RATE": rate, "DURATION_S": duration + 14, "PRE_VUS": max(50, int(rate * 0.05)),
                     "MAX_VUS": 600, "BASE_URL": base}
        import threading
        res = {}
        t = threading.Thread(target=lambda: res.setdefault("k6", _run_k6_host(env, out_dir, "profile_load", k6_params)))
        t.start()
        time.sleep(5)  # beban sudah steady
        if app == "go":
            fetch("http://127.0.0.1:6060/debug/pprof/profile?seconds=%d" % duration, os.path.join(out_dir, "cpu.pb.gz"), duration + 30)
            for kind in ("heap", "allocs", "goroutine"):
                fetch("http://127.0.0.1:6060/debug/pprof/%s" % kind, os.path.join(out_dir, "%s.pb.gz" % kind), 30)
        else:
            sample_file = os.path.join(out_dir, "sample.txt")
            xc = None
            if shutil.which("xcrun"):
                trace = os.path.join(out_dir, "timeprofiler.trace")
                if os.path.exists(trace):
                    shutil.rmtree(trace, ignore_errors=True)
                xc = subprocess.Popen(["xcrun", "xctrace", "record", "--template", "Time Profiler", "--attach", str(pid), "--time-limit",
                                       "%ds" % duration, "--output", trace, "--no-prompt"], stdout=open(os.path.join(out_dir, "xctrace.log"), "w"),
                                      stderr=subprocess.STDOUT)
            subprocess.run(["sample", str(pid), str(duration), "-file", sample_file], check=True, capture_output=True)
            if xc:
                try:
                    xc.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    xc.terminate()
        t.join(timeout=duration + 60)
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    summary = {"app": app, "scenario": scenario, "duration_s": duration, "rate_rps": rate, "rate_basis": rate_note,
               "binary": os.path.relpath(binp, ROOT), "label": "penjelasan, bukan perbandingan (macOS native, bukan VM Docker)",
               "profiler_active_only_in_this_run": True}
    if app == "go":
        pb = os.path.join(out_dir, "cpu.pb.gz")
        rows, head = top_go(pb)
        summary.update(top10=rows, top10_source="go tool pprof -top (flat) pada cpu.pb.gz", pprof_header=head)
        traces = subprocess.run(["go", "tool", "pprof", "-traces", pb], capture_output=True, text=True).stdout
        stacks = parse_traces(traces)
        open(os.path.join(out_dir, "cpu_flame.svg"), "w").write(to_svg(stacks, "Go CPU profile %s" % scenario))
        for kind in ("heap", "allocs", "goroutine"):
            p = os.path.join(out_dir, kind + ".pb.gz")
            tr = subprocess.run(["go", "tool", "pprof", "-top", "-nodecount=10", p], capture_output=True, text=True).stdout
            open(os.path.join(out_dir, kind + "_top.txt"), "w").write(tr)
        summary["svg_note"] = "Graphviz (dot) tidak terpasang: SVG berupa flame graph buatan tools/lib/flame.py dari pprof -traces, bukan 'pprof -svg'"
        # profil PGO untuk varian tuned (S13)
        pgo_dir = os.path.join(ROOT, "go-app", "pgo")
        os.makedirs(pgo_dir, exist_ok=True)
        with gzip.open(pb, "rb") as fi, open(os.path.join(pgo_dir, "default.pgo"), "wb") as fo:
            shutil.copyfileobj(fi, fo)
        summary["pgo_exported"] = "go-app/pgo/default.pgo (dipakai varian tuned S13 lewat GO_PGO=1)"
    else:
        rows = top_sample(os.path.join(out_dir, "sample.txt"))
        summary.update(top10=rows, top10_source="macOS sample: 'Sort by top of stack'",
                       xctrace=os.path.exists(os.path.join(out_dir, "timeprofiler.trace")))
    json.dump(summary, open(os.path.join(out_dir, "top10.json"), "w"), indent=1)
    log("selesai: %s" % out_dir)
    for r in summary.get("top10", []):
        log("  %s" % json.dumps(r))


def _run_k6_host(env, out_dir, name, params):
    """k6 di container menembak aplikasi native lewat host.docker.internal; ringkasan ditulis ke out_dir/k6/."""
    rel = os.path.relpath(os.path.join(out_dir, "k6"), RESULTS)
    cmd = ["docker", "exec"]
    for k, v in dict({"SEED": "20261013"}, **params).items():
        cmd += ["-e", "%s=%s" % (k, v)]
    cmd += ["bench-k6", "k6", "run", "--quiet", "--no-color", "--summary-export", "/results/%s/%s.json" % (rel, name), "/loadtest/main.js"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("k6 gagal: " + (r.stdout + r.stderr)[-500:])
    return True


if __name__ == "__main__":
    main()
