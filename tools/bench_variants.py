"""S13 (varian tuned + sapuan pool) dan S14 (skala vertikal). Dipanggil dari bench.py."""
import json
import os

from benchenv import APP_SERVICES, dc, log
from runner import update_infra_cpusets, with_cpus

# BENCH_SMOKE=1 memakai durasi pendek (uji alur); TUNED_SCENARIOS/POOLS/SWEEP_SCENARIOS membatasi cakupan saat uji singkat.
TUNED_SCENARIOS = [x for x in os.environ.get("TUNED_SCENARIOS", "s3,s4,s8").split(",") if x]
POOLS = [int(x) for x in os.environ.get("POOLS", "8,16,32,64").split(",") if x]
SWEEP_SCENARIOS = [x for x in os.environ.get("SWEEP_SCENARIOS", "s3,s8").split(",") if x]
SMOKE = os.environ.get("BENCH_SMOKE") == "1"


def build_images(bench, env, apps):
    for variant in ("default", "tuned"):
        e = dict(env, VARIANT=variant)
        for app in apps:
            dc(["build", APP_SERVICES[app]], env=e)


def run_tuned(env, bench):
    e = dict(env, VARIANT="tuned")
    ctx = bench.Ctx(e, "tuned", smoke=SMOKE)
    P = ctx.P
    kinit, ov = 3, 12
    a = ov + P["warmup"] + sum(P["ramp"] + P["steady"] + kinit for _ in P["vus"])
    b = ov + P["warmup"] + sum(P["b_s"] + kinit for _ in P["b_fracs"])
    est = ctx.repeats * len(ctx.apps) * (len(TUNED_SCENARIOS) * (a + b) + len(SWEEP_SCENARIOS) * len(POOLS) * a)
    log("S13 tuned | run-id %s | apps=%s repeats=%d" % (ctx.run_id, ",".join(ctx.apps), ctx.repeats))
    log("Estimasi durasi: ~%s (tuned: %s tahap A+B; sapuan pool %s pada %s tahap A)" % (
        bench.fmt_dur(est), ",".join(TUNED_SCENARIOS), POOLS, ",".join(SWEEP_SCENARIOS)))
    build_images(bench, e, ctx.apps)
    from runner import ensure_infra
    ensure_infra(e)
    update_infra_cpusets(e)
    bench.collect_meta(ctx)
    pgo = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "go-app", "pgo", "default.pgo"))
    json.dump({"pgo_profile_present": pgo}, open(os.path.join(ctx.out, "tuned_notes.json"), "w"))
    if not pgo:
        log("CATATAN: go-app/pgo/default.pgo tidak ada -> PGO TIDAK dipakai pada tuned Go (jalankan 'make profile APP=go' lalu ulangi).")
    # 1) varian tuned pada S3, S4, S8 (tahap A dan B; laju B = laju default agar resource sebanding)
    for sc in TUNED_SCENARIOS:
        base = bench.latest_saturation(ctx, sc)
        if base:
            log("   laju tahap B untuk %s memakai saturasi default %.1f RPS (run default terakhir)" % (sc.upper(), base))
        else:
            log("   peringatan: belum ada run default untuk %s; laju B memakai saturasi tuned sendiri" % sc.upper())
        bench.run_scenario(ctx, sc, stages=("A", "B"), fixed_rates=base)
    # 2) sapuan ukuran pool koneksi total (konfigurasi default, hanya pool yang berubah; sama untuk kedua stack)
    for sc in SWEEP_SCENARIOS:
        for pool in POOLS:
            log("-- sapuan pool %d pada %s (default)" % (pool, sc.upper()))
            bench.run_scenario(ctx, sc, stages=("A",), env_over={"VARIANT": "default", "DB_POOL_TOTAL": str(pool)}, tag="pool%d" % pool)
    log("\nselesai. Hasil: results/raw/%s" % ctx.run_id)


def run_scale(env, bench):
    cpus = [int(x) for x in env.get("SCALE_CPUS", "1,2,3").split(",")]
    ctx = bench.Ctx(env, "scale", smoke=SMOKE)
    P = ctx.P
    kinit, ov = 3, 12
    a = ov + P["warmup"] + sum(P["ramp"] + P["steady"] + kinit for _ in P["vus"])
    est = ctx.repeats * len(ctx.apps) * len(cpus) * 2 * a
    log("S14 skala vertikal | run-id %s | CPU=%s | apps=%s repeats=%d" % (ctx.run_id, cpus, ",".join(ctx.apps), ctx.repeats))
    log("Estimasi durasi: ~%s. Kesimpulan hanya berlaku untuk 1 sampai 3 core." % bench.fmt_dur(est))
    for app in ctx.apps:
        dc(["build", APP_SERVICES[app]], env=env)
    from runner import ensure_infra
    ensure_infra(env)
    bench.collect_meta(ctx)
    try:
        for n in cpus:
            en = with_cpus(env, n)
            # tata letak cpuset khusus skala: app 0..n-1, postgres 3-4, k6 5-6, sampler 7 (tanpa tumpang tindih untuk n <= 3)
            en.update(PG_CPUSET="3-4", K6_CPUSET="5-6", SAMPLER_CPUSET="7")
            update_infra_cpusets(en)
            over = {k: en[k] for k in ("APP_CPUS", "APP_CPUSET", "DB_POOL_TOTAL", "EVENT_LOOPS", "GOMAXPROCS_APP", "PG_CPUSET", "K6_CPUSET", "SAMPLER_CPUSET")}
            for sc in ("s3", "s8"):
                log("-- CPU aplikasi = %d, pool = %d, %s tahap A" % (n, 8 * n, sc.upper()))
                bench.run_scenario(ctx, sc, stages=("A",), env_over=over, tag="cpu%d" % n)
    finally:
        update_infra_cpusets(env)
    log("\nselesai. Hasil: results/raw/%s" % ctx.run_id)


def main(cmd, env, bench):
    {"tuned": run_tuned, "scale": run_scale}[cmd](env, bench)
