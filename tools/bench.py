#!/usr/bin/env python3
"""Orkestrator benchmark beban (selalu di container). Pakai lewat Makefile:

  bench.py smoke                      make bench-smoke
  bench.py run --scenarios s1,s3,s8   make bench / bench-core
  bench.py tuned                      make bench-tuned   (S13)
  bench.py scale                      make scale-bench   (S14)

Aturan: satu aplikasi aktif; DB direset dari template + statistik Postgres di-reset + container di-restart sebelum tiap run;
urutan Go/Swift diselang-seling dan diacak; run dibuang dan diulang bila CPU k6 > 80% atau thermal throttling.
"""
import argparse
import json
import os
import random
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from benchenv import APP_CONTAINERS, APP_SERVICES, ROOT, container_info, load_env, log, psql, sh  # noqa: E402
from runner import (RESULTS, Sampler, ensure_infra, log_stats, pg_snapshot, probe, prepare_app, run_k6, run_point,  # noqa: E402
                    saturation_of, thermal, update_infra_cpusets, wait_thermal_normal, with_cpus, go_runtime, k6_numbers)

CORE = ["s1", "s3", "s4", "s8"]
ALL = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10", "s11"]
SCEN_DESC = {"s1": "GET /bench/json", "s2": "POST /bench/echo", "s3": "GET /users/{id}", "s4": "GET /users/{id}/orders",
             "s5": "GET /users/{id}?include=orders", "s6": "POST /orders", "s7": "PUT /orders/{id}", "s8": "campuran 50/20/10/10/10",
             "s9": "POST /orders/{id}/pay", "s10": "soak S8 pada 70% saturasi", "s11": "biaya logging S8 (quiet vs access)"}


def plan_params(env, smoke):
    if smoke:
        return dict(warmup=3, vus=[32, 128], ramp=1, steady=4, b_s=5, b_fracs=[0.5], soak_seg=5, soak_segments=3)
    return dict(warmup=int(env["WARMUP_S"]), vus=[int(x) for x in env["STAGE_A_VUS"].split(",")],
                ramp=int(env["STAGE_A_RAMP_S"]), steady=int(env["STAGE_A_STEADY_S"]), b_s=int(env["STAGE_B_S"]),
                b_fracs=[0.25, 0.5, 0.75], soak_seg=60, soak_segments=max(1, int(env["SOAK_S"]) // 60))


def parse_scenarios(s):
    if s == "core":
        return CORE
    if s == "all":
        return ALL
    out = [x.strip().lower() for x in s.split(",") if x.strip()]
    bad = [x for x in out if x not in ALL]
    if bad:
        raise SystemExit("skenario tidak dikenal: %s (valid: %s; s12 -> make startup-bench, s13 -> make bench-tuned, s14 -> make scale-bench)" % (bad, ALL))
    return out


class Ctx:
    def __init__(self, env, cmd, smoke=False, apps=None, repeats=None):
        self.env = env
        self.smoke = smoke
        self.P = plan_params(env, smoke)
        self.apps = apps or (["go", "swift"] if env.get("APP", "both") == "both" else [env["APP"]])
        self.repeats = repeats or (1 if smoke else int(env["REPEATS"]))
        self.run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + cmd + ("-smoke" if smoke else "")
        self.out = os.path.join(RESULTS, "raw", self.run_id)
        os.makedirs(self.out, exist_ok=True)
        self.points_f = open(os.path.join(self.out, "points.jsonl"), "a")
        self.runs_f = open(os.path.join(self.out, "runs.jsonl"), "a")
        self.saturation = {}
        self.slo = float(env["SLO_P99_MS"])

    def order(self, key, r):
        rnd = random.Random("%s|%s" % (self.run_id, key))
        base = list(self.apps)
        rnd.shuffle(base)
        return base if r % 2 == 0 else list(reversed(base))  # diselang-seling antar ulangan

    def write_point(self, rec):
        self.points_f.write(json.dumps(rec) + "\n")
        self.points_f.flush()

    def write_run(self, rec):
        self.runs_f.write(json.dumps(rec) + "\n")
        self.runs_f.flush()

    def save_saturation(self):
        json.dump(self.saturation, open(os.path.join(self.out, "saturation.json"), "w"), indent=1)


# ---------------------------------------------------------------- metadata
def collect_meta(ctx):
    env = ctx.env

    def out(cmd):
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return r.stdout.strip()

    meta = {
        "run_id": ctx.run_id, "label": "smoke, bukan final" if ctx.smoke else "benchmark",
        "scope": "Apple Silicon, Docker VM: hasil relatif, bukan absolut",
        "mac_model": out("sysctl -n hw.model"), "sw_vers": out("sw_vers | tr '\\n' ' '"), "hw_ncpu": out("sysctl -n hw.ncpu"),
        "perf_cores": out("sysctl -n hw.perflevel0.physicalcpu"), "eff_cores": out("sysctl -n hw.perflevel1.physicalcpu"),
        "hw_memsize": out("sysctl -n hw.memsize"), "ulimit_n": out("ulimit -n"),
        "docker_version": out("docker version --format '{{.Server.Version}}'"),
        "docker_engine": out("docker info --format '{{.OperatingSystem}}'"),
        "docker_vm_cpus": out("docker info --format '{{.NCPU}}'"), "docker_vm_mem_bytes": out("docker info --format '{{.MemTotal}}'"),
        "cgroup_version": out("docker info --format '{{.CgroupVersion}}'"),
        "profile": env["PROFILE"], "image_flavor": env["IMAGE_FLAVOR"], "variant": env["VARIANT"], "log_mode": env["LOG_MODE"],
        "slo_p99_ms": env["SLO_P99_MS"], "repeats": ctx.repeats, "apps": ctx.apps,
        "limits": {k: env[k] for k in ("APP_CPUS", "APP_CPUSET", "APP_MEM", "PG_CPUS", "PG_CPUSET", "PG_MEM", "K6_CPUS", "K6_CPUSET", "K6_MEM", "DB_POOL_TOTAL", "EVENT_LOOPS")},
        "plan": ctx.P, "thermal_before": thermal(),
        "images": {k: env[k] for k in ("GO_BUILD_IMAGE", "SWIFT_BUILD_IMAGE", "DISTROLESS_STATIC_IMAGE", "DISTROLESS_CC_IMAGE", "ALPINE_IMAGE", "PG_IMAGE", "K6_IMAGE")},
        "app_images": {a: out("docker image inspect bench-%s:%s --format '{{.Id}} {{.Size}}'" % (a, env["IMAGE_FLAVOR"])) for a in ("go", "swift")},
        "k6_version": out("docker exec bench-k6 k6 version"), "postgres_version": out("docker exec bench-postgres postgres --version"),
        "seed_checksums": open(os.path.join(ROOT, "db", "checksums.txt")).read().strip().splitlines(),
        "git_commit": out("git -C %s rev-parse --short HEAD" % ROOT),
        "sampler_mode": "cgroup v2 (pid=host, cgroupns=host) + docker stats sebagai pembanding silang",
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    json.dump(meta, open(os.path.join(ctx.out, "meta.json"), "w"), indent=1)
    return meta


# ---------------------------------------------------------------- satu run (restart + reset + warmup + titik-titik)
def point_spec_A(ctx):
    P = ctx.P
    return [dict(label="vu%d" % v, mode="vus", params={"VUS": v, "RAMP_S": P["ramp"], "STEADY_S": P["steady"]}, steady=P["steady"], ramp=P["ramp"]) for v in P["vus"]]


def point_spec_B(ctx, rates):
    P = ctx.P
    out = []
    for rate, frac in rates:
        pre = max(50, int(rate * 0.05))
        out.append(dict(label="rate%d" % rate, frac=frac, mode="rate",
                        params={"RATE": rate, "DURATION_S": P["b_s"], "PRE_VUS": pre, "MAX_VUS": 600}, steady=P["b_s"], ramp=0))
    return out


def execute_run(ctx, app, scenario, stage, repeat, specs, tag=None, env_over=None, extra=None):
    env = dict(ctx.env)
    if env_over:
        env.update(env_over)
    name = "%s_%s_%s_r%d%s" % (app, scenario, stage, repeat, ("_" + tag) if tag else "")
    rd = os.path.join(ctx.out, name)
    os.makedirs(rd, exist_ok=True)
    log("  [run] %s" % name)
    wait_thermal_normal()
    prepare_app(app, env, tag_env=env_over)
    samp = Sampler(env, app, rd)
    samp.start()
    time.sleep(1.5)
    pg_snapshot(os.path.join(rd, "pg_before.json"))
    rt_before = go_runtime() if app == "go" else None
    ls0 = log_stats(app)
    points = []
    try:
        w = run_k6(env, app, rd, "warmup", {"SCENARIO": scenario, "MODE": "warmup", "VUS": 32, "DURATION_S": ctx.P["warmup"]})
        warm_reqs = int(w["metrics"]["http_reqs"]["count"] if "count" in w["metrics"]["http_reqs"] else w["metrics"]["http_reqs"]["values"]["count"])
        for spec in specs:
            for attempt in range(3):
                params = dict(spec["params"], SCENARIO=scenario)
                pt = run_point(env, app, rd, spec["label"], spec["mode"], params, spec["steady"], spec["ramp"], ctx.slo)
                if pt["valid"]:
                    break
                log("    titik %s tidak valid (%s): diulang (%d/3)" % (spec["label"], ",".join(pt["flags"]), attempt + 1))
                wait_thermal_normal()
            pt.update({"run_id": ctx.run_id, "app": app, "scenario": scenario, "stage": stage, "repeat": repeat, "tag": tag,
                       "variant": env["VARIANT"], "flavor": env["IMAGE_FLAVOR"], "log_mode": env["LOG_MODE"], "profile": env["PROFILE"],
                       "pool_total": int(env["DB_POOL_TOTAL"]), "app_cpus": int(env["APP_CPUS"]), "smoke": ctx.smoke,
                       "run_dir": os.path.relpath(rd, RESULTS), "frac": spec.get("frac"), "attempts": attempt + 1})
            pt.update(extra or {})
            if not pt["valid"]:
                pt["flags"].append("gave_up_after_retries")
            ctx.write_point(pt)
            points.append(pt)
            log("    %-8s rps=%9.1f p99=%7.2fms err=%.4f cpu=%.2f cores mem_peak=%.0fMB %s" % (
                spec["label"], pt["rps"], pt["lat_ms"]["p(99)"] or -1, pt["err_rate"], (pt["res"] or {}).get("cpu_cores", -1),
                (pt["res"] or {}).get("mem_peak_mb", -1), ",".join(pt["flags"])))
    finally:
        samp.stop()
    pg_snapshot(os.path.join(rd, "pg_after.json"))
    ls1 = log_stats(app)
    total_req = warm_reqs + sum(p["req_total"] for p in points)
    rt_after = go_runtime() if app == "go" else None
    info = container_info(APP_CONTAINERS[app])
    ctx.write_run({"run_id": ctx.run_id, "name": name, "app": app, "scenario": scenario, "stage": stage, "repeat": repeat, "tag": tag,
                   "run_dir": os.path.relpath(rd, RESULTS), "variant": env["VARIANT"], "flavor": env["IMAGE_FLAVOR"],
                   "log_mode": env["LOG_MODE"], "log_lines": ls1["lines"] - ls0["lines"], "log_bytes": ls1["bytes"] - ls0["bytes"],
                   "requests_total_incl_warmup": total_req,
                   "log_lines_per_req": (ls1["lines"] - ls0["lines"]) / max(1, total_req),
                   "log_bytes_per_req": (ls1["bytes"] - ls0["bytes"]) / max(1, total_req),
                   "container": {"image": info["Image"], "cpuset": info["HostConfig"]["CpusetCpus"], "nano_cpus": info["HostConfig"]["NanoCpus"],
                                 "memory": info["HostConfig"]["Memory"], "user": info["Config"]["User"]},
                   "go_runtime_before": rt_before, "go_runtime_after": rt_after})
    return points


# ---------------------------------------------------------------- skenario A/B
def median(xs):
    return statistics.median(xs) if xs else 0.0


def run_scenario(ctx, sc, stages=("A", "B"), env_over=None, tag=None, fixed_rates=None):
    log("== %s (%s)" % (sc.upper(), SCEN_DESC[sc]))
    sat = {a: [] for a in ctx.apps}
    fallback = False
    if "A" in stages:
        for r in range(ctx.repeats):
            for app in ctx.order(sc + "A", r):
                pts = execute_run(ctx, app, sc, "A", r, point_spec_A(ctx), tag=tag, env_over=env_over)
                s, fb = saturation_of(pts, ctx.slo)
                sat[app].append(s)
                fallback |= fb
        med = {a: median(v) for a, v in sat.items()}
        slower = min(med.values()) if med else 0.0
        ctx.saturation[sc + (("_" + tag) if tag else "")] = {"per_app_median": med, "per_app_all": sat, "slower": slower, "fallback": fallback}
        ctx.save_saturation()
        log("   saturasi (RPS, median): %s -> yang lebih lambat: %.1f%s" % (json.dumps({a: round(v, 1) for a, v in med.items()}), slower,
                                                                          " (FALLBACK: tidak ada titik lolos SLO)" if fallback else ""))
    if "B" in stages:
        base = fixed_rates if fixed_rates else ctx.saturation[sc + (("_" + tag) if tag else "")]["slower"]
        rates = [(max(1, int(round(base * f))), f) for f in ctx.P["b_fracs"]]
        for r in range(ctx.repeats):
            for app in ctx.order(sc + "B", r):
                execute_run(ctx, app, sc, "B", r, point_spec_B(ctx, rates), tag=tag, env_over=env_over)


def latest_saturation(ctx, sc):
    """Saturasi dari run sebelumnya (profil + flavor sama, bukan smoke bila run ini bukan smoke)."""
    base = os.path.join(RESULTS, "raw")
    for d in sorted(os.listdir(base), reverse=True):
        p = os.path.join(base, d, "saturation.json")
        if os.path.exists(p) and d != ctx.run_id and (("smoke" in d) == ctx.smoke):
            try:
                s = json.load(open(p))
                if sc in s and s[sc]["slower"] > 0:
                    return s[sc]["slower"]
            except Exception:
                pass
    return None


def ensure_saturation(ctx, sc):
    if sc in ctx.saturation:
        return ctx.saturation[sc]["slower"]
    prev = latest_saturation(ctx, sc)
    if prev:
        ctx.saturation[sc] = {"slower": prev, "from_previous_run": True}
        log("   saturasi %s dipakai dari run sebelumnya: %.1f RPS" % (sc.upper(), prev))
        return prev
    log("   saturasi %s belum ada: menjalankan tahap A dulu" % sc.upper())
    run_scenario(ctx, sc, stages=("A",))
    return ctx.saturation[sc]["slower"]


def run_soak(ctx):
    """S10: S8 pada 70% RPS saturasi, segmen 60 detik berurutan tanpa restart (drift p99, tren memori/thread)."""
    sat = ensure_saturation(ctx, "s8")
    rate = max(1, int(round(0.7 * sat)))
    P = ctx.P
    log("== S10 soak: %d segmen x %ds pada %d RPS (70%% saturasi S8)" % (P["soak_segments"], P["soak_seg"], rate))
    for r in range(ctx.repeats):
        for app in ctx.order("s10", r):
            specs = []
            for i in range(P["soak_segments"]):
                specs.append(dict(label="seg%02d" % i, frac=0.7, mode="rate", steady=P["soak_seg"], ramp=0,
                                  params={"RATE": rate, "DURATION_S": P["soak_seg"], "PRE_VUS": max(50, int(rate * 0.05)), "MAX_VUS": 600}))
            execute_run(ctx, app, "s10", "SOAK", r, specs, extra={"soak": True})


def run_logcost(ctx):
    """S11: S8 pada laju tetap 50% saturasi, mode quiet lalu access (per stack)."""
    sat = ensure_saturation(ctx, "s8")
    rate = max(1, int(round(0.5 * sat)))
    log("== S11 biaya logging: S8 pada %d RPS (50%% saturasi), quiet lalu access" % rate)
    for r in range(ctx.repeats):
        for app in ctx.order("s11", r):
            for mode in ("quiet", "access"):
                execute_run(ctx, app, "s11", "B", r, point_spec_B(ctx, [(rate, 0.5)]), tag=mode, env_over={"LOG_MODE": mode},
                            extra={"s11_mode": mode})


# ---------------------------------------------------------------- estimasi
def estimate_seconds(ctx, scenarios):
    P = ctx.P
    per_run_overhead = 25
    kinit = 3
    a = per_run_overhead + P["warmup"] + sum(P["ramp"] + P["steady"] + kinit for _ in P["vus"])
    b = per_run_overhead + P["warmup"] + sum(P["b_s"] + kinit for _ in P["b_fracs"])
    total = 0
    n_apps = len(ctx.apps)
    for sc in scenarios:
        if sc == "s10":
            total += ctx.repeats * n_apps * (per_run_overhead + P["warmup"] + P["soak_segments"] * (P["soak_seg"] + kinit))
        elif sc == "s11":
            total += ctx.repeats * n_apps * 2 * (per_run_overhead + P["warmup"] + P["b_s"] + kinit)
        else:
            total += ctx.repeats * n_apps * (a + b)
    return total


def fmt_dur(s):
    h, rem = divmod(int(s), 3600)
    return "%dj %02dm" % (h, rem // 60) if h else "%dm %02ds" % (rem // 60, rem % 60)


def run_scenarios(ctx, scenarios):
    for sc in scenarios:
        if sc == "s10":
            run_soak(ctx)
        elif sc == "s11":
            run_logcost(ctx)
        else:
            run_scenario(ctx, sc)


def start(ctx, scenarios, title):
    log("%s | run-id %s | apps=%s repeats=%d profil=%s flavor=%s variant=%s" % (
        title, ctx.run_id, ",".join(ctx.apps), ctx.repeats, ctx.env["PROFILE"], ctx.env["IMAGE_FLAVOR"], ctx.env["VARIANT"]))
    est = estimate_seconds(ctx, scenarios)
    log("Estimasi durasi: ~%s (skenario: %s)" % (fmt_dur(est), ",".join(scenarios)))
    for app in ctx.apps:  # image harus ada dan sesuai flavor
        from benchenv import dc
        dc(["build", APP_SERVICES[app]], env=ctx.env)
    ensure_infra(ctx.env)
    update_infra_cpusets(ctx.env)
    collect_meta(ctx)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke")
    r = sub.add_parser("run")
    r.add_argument("--scenarios", default=None)
    sub.add_parser("tuned")
    sub.add_parser("scale")
    a = ap.parse_args()
    env = load_env()
    t0 = time.time()

    if a.cmd == "smoke":
        ctx = Ctx(env, "bench", smoke=True)
        scenarios = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"]
        start(ctx, scenarios, "SMOKE (angka berlabel 'smoke, bukan final')")
        run_scenarios(ctx, scenarios)
    elif a.cmd == "run":
        scenarios = parse_scenarios(a.scenarios or env.get("SCENARIO", "core"))
        ctx = Ctx(env, "bench")
        start(ctx, scenarios, "BENCH")
        run_scenarios(ctx, scenarios)
    elif a.cmd in ("tuned", "scale"):
        import bench_variants
        bench_variants.main(a.cmd, env, sys.modules[__name__])
        return
    log("\nselesai dalam %s. Hasil: results/raw/%s | buat laporan: make report" % (fmt_dur(time.time() - t0), ctx.run_id))


if __name__ == "__main__":
    main()
