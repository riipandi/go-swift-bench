#!/usr/bin/env python3
"""make report: results/report.md, CSV agregat, dan grafik (SVG + PNG) dari results/raw. Semua angka berasal dari run nyata.

Aturan kesimpulan (PRD/ADR-013): satu stack 'lebih baik' hanya bila rentang min-maks kedua stack tidak tumpang tindih DAN selisih
median > 5%; selain itu 'setara' atau 'belum cukup bukti'. DX4 tanpa skor. Penyebab selisih tidak disimpulkan tanpa data profil.
"""
import csv
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
from benchenv import ROOT  # noqa: E402
import svgchart  # noqa: E402
from stats import cell, fmt_ratio, judge, ratio, slope, stat  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
RAW = os.path.join(RESULTS, "raw")
CHARTS = os.path.join(RESULTS, "charts")
APPS = ["go", "swift"]
SCEN_NAME = {"s1": "S1 GET /bench/json", "s2": "S2 POST /bench/echo", "s3": "S3 GET /users/{id}", "s4": "S4 GET /users/{id}/orders",
             "s5": "S5 GET /users/{id}?include=orders", "s6": "S6 POST /orders", "s7": "S7 PUT /orders/{id}", "s8": "S8 campuran",
             "s9": "S9 POST /orders/{id}/pay", "s10": "S10 soak", "s11": "S11 biaya logging"}
LABEL_LOAD = "Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut"
LABEL_NATIVE = "macOS native"
out = []
warnings = []
csv_rows = {}


def w(s=""):
    out.append(s)


def md_table(headers, rows):
    w("| " + " | ".join(headers) + " |")
    w("|" + "|".join(["---"] * len(headers)) + "|")
    for r in rows:
        w("| " + " | ".join(str(c) for c in r) + " |")
    w()


def load_jsonl(p):
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def get(d, path, default=None):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


# ------------------------------------------------------------------ pemuatan data
def load_load_runs():
    runs = []
    if not os.path.isdir(RAW):
        return runs
    for d in sorted(os.listdir(RAW)):
        p = os.path.join(RAW, d)
        if not os.path.exists(os.path.join(p, "points.jsonl")):
            continue
        kind = "scale" if d.endswith("-scale") else "tuned" if d.endswith("-tuned") else "smoke" if d.endswith("-smoke") else "bench"
        meta = json.load(open(os.path.join(p, "meta.json"))) if os.path.exists(os.path.join(p, "meta.json")) else {}
        sat = json.load(open(os.path.join(p, "saturation.json"))) if os.path.exists(os.path.join(p, "saturation.json")) else {}
        runs.append({"id": d, "kind": kind, "dir": p, "meta": meta, "points": load_jsonl(os.path.join(p, "points.jsonl")),
                     "runs": load_jsonl(os.path.join(p, "runs.jsonl")), "saturation": sat})
    return runs


def latest_dir(sub):
    base = os.path.join(RAW, sub)
    if not os.path.isdir(base):
        return None
    ds = sorted(d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d)) and not d.startswith(("_", ".")))
    return os.path.join(base, ds[-1]) if ds else None


def metric_values(points, path):
    return [get(p, path) for p in points if get(p, path) is not None]


# ------------------------------------------------------------------ bagian beban
def default_points(runs):
    """Titik default: utamakan run penuh; jika tidak ada pakai smoke (diberi label)."""
    full = [r for r in runs if r["kind"] == "bench"]
    src = full if full else [r for r in runs if r["kind"] == "smoke"]
    label = "benchmark" if full else "smoke, bukan final"
    pts = []
    for r in src:
        pts += r["points"]
    return pts, label, src


def group(points, keyfn):
    g = {}
    for p in points:
        g.setdefault(keyfn(p), []).append(p)
    return g


def section_load(runs):
    pts, label, src = default_points(runs)
    if not pts:
        w("## Hasil beban\n\nBelum ada run beban. Jalankan `make bench-smoke` atau `make bench-core`.\n")
        return {}
    w("## Hasil beban (default)")
    w()
    w("> **%s.** Sumber: %s. Run: %s." % (LABEL_LOAD, "angka " + label.upper() if label.startswith("smoke") else label, ", ".join(r["id"] for r in src)))
    w("> **Definisi memori.** `anon` = memori privat proses (stabil, dipakai untuk kesimpulan); `cgroup peak` = `memory.peak` yang ikut menghitung page cache berkas yang dibebankan ke cgroup pertama yang menyentuhnya, sehingga tidak deterministik antar run.")
    if label.startswith("smoke"):
        w("> **Angka smoke, bukan final:** 1 ulangan, durasi dipangkas; tidak ada kesimpulan yang lolos aturan (butuh ≥ 2 ulangan).")
    w()
    main = [p for p in pts if p["variant"] == "default" and not p.get("tag") and p["stage"] in ("A", "B") and p["scenario"] not in ("s10", "s11")]
    scen = sorted({p["scenario"] for p in main}, key=lambda s: int(s[1:]))
    summary = {}
    for sc in scen:
        w("### %s" % SCEN_NAME.get(sc, sc))
        w()
        A = group([p for p in main if p["scenario"] == sc and p["stage"] == "A"], lambda p: (p["app"], int(p["params"]["VUS"])))
        vus = sorted({k[1] for k in A})
        rows = []
        for v in vus:
            row = [v]
            for app in APPS:
                pp = A.get((app, v), [])
                s = stat([p["rps"] for p in pp])
                p99 = stat([p["lat_ms"]["p(99)"] for p in pp])
                er = stat([p["err_rate"] for p in pp])
                row += [cell(s, 0), cell(p99, 1), "%.4f" % er["max"] if er else "–"]
            rows.append(row)
        w("**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]")
        w()
        md_table(["VU", "Go RPS", "Go p99 ms", "Go err maks", "Swift RPS", "Swift p99 ms", "Swift err maks"], rows)
        # saturasi
        sat_by_app = {}
        for app in APPS:
            vals = []
            for r in src:
                s = r["saturation"].get(sc)
                if s and "per_app_all" in s:
                    vals += s["per_app_all"].get(app, [])
            sat_by_app[app] = stat(vals)
        if any(sat_by_app.values()):
            ver = judge(sat_by_app["go"], sat_by_app["swift"], lower_better=False)
            w("**Titik saturasi** (RPS tertinggi dengan error < 0,1%% dan p99 < SLO): Go %s, Swift %s; rasio Swift/Go %s → %s" % (
                cell(sat_by_app["go"], 0), cell(sat_by_app["swift"], 0), fmt_ratio(ratio(sat_by_app["go"], sat_by_app["swift"])), ver[1]))
            w()
            summary[sc] = {"sat": sat_by_app, "verdict": ver}
        if vus:
            ku = {app: stat([p["k6_util"] for p in A.get((app, max(vus)), [])]) for app in APPS}
            w("Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go %s, Swift %s. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database)." % (
                cell(ku["go"], 2), cell(ku["swift"], 2)))
            w()
        # tahap B
        B = group([p for p in main if p["scenario"] == sc and p["stage"] == "B"], lambda p: (p["app"], p.get("frac")))
        fr = sorted({k[1] for k in B if k[1] is not None})
        rows = []
        for f in fr:
            for app in APPS:
                pp = B.get((app, f), [])
                if not pp:
                    continue
                rate = pp[0]["params"].get("RATE")
                rows.append(["%d%% (%s RPS)" % (round(f * 100), rate), app,
                             cell(stat([p["lat_ms"]["p(50)" if False else "med"] for p in pp]), 2),
                             cell(stat([p["lat_ms"]["p(99)"] for p in pp]), 2),
                             cell(stat([get(p, "res.cpu_cores") for p in pp]), 2),
                             cell(stat([get(p, "res.cpu_user_cores") for p in pp]), 2) + " / " + cell(stat([get(p, "res.cpu_sys_cores") for p in pp]), 2),
                             cell(stat([p["cpu_ms_per_req"] for p in pp]), 3),
                             cell(stat([get(p, "res.mem_anon_max_mb") for p in pp]), 0) + " / " + cell(stat([get(p, "res.mem_peak_mb") for p in pp]), 0),
                             cell(stat([get(p, "res.threads_max") for p in pp]), 0),
                             cell(stat([get(p, "res.fds_max") for p in pp]), 0),
                             cell(stat([p["queries_per_req"] for p in pp]), 2),
                             cell(stat([p["dropped"] for p in pp]), 0)])
        if rows:
            w("**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**")
            w()
            md_table(["Laju (% saturasi yang lebih lambat)", "App", "p50 ms", "p99 ms", "CPU core", "CPU user / sys", "CPU-ms/req", "Mem anon maks / cgroup peak MB", "Thread maks", "FD maks", "Query/req", "Dropped"], rows)
        # turunan pada saturasi tertinggi A
        rows = []
        if vus:
            vmax = max(vus)
            for app in APPS:
                pp = A.get((app, vmax), [])
                if pp:
                    rows.append([app, vmax, cell(stat([p["rps_per_core"] for p in pp]), 0), cell(stat([p["rps_per_gb_anon"] for p in pp if p.get("rps_per_gb_anon")]), 0) + " / " + cell(stat([p["rps_per_gb_peak"] for p in pp]), 0),
                                 cell(stat([p["cpu_ms_per_req"] for p in pp]), 3), cell(stat([get(p, "pg_util") for p in pp]), 2)])
            if rows:
                w("**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**")
                w()
                md_table(["App", "VU", "RPS per core terpakai", "RPS per GB mem (anon maks / cgroup peak)", "CPU-ms/req", "Util. Postgres"], rows)
        # rasio
        if vus:
            ratios = []
            for v in (vus[0], vus[-1]):
                sg, ss = stat([p["rps"] for p in A.get(("go", v), [])]), stat([p["rps"] for p in A.get(("swift", v), [])])
                ratios.append("VU %d: %s" % (v, fmt_ratio(ratio(sg, ss))))
            w("Rasio RPS Swift/Go (median [rentang konservatif]): " + "; ".join(ratios))
            w()
        for p in main:
            if p["scenario"] == sc:
                for fl in p.get("flags", []):
                    warnings.append("%s %s %s %s: %s" % (p["run_id"], p["app"], sc, p["label"], fl))
        aggk = group([p for p in main if p["scenario"] == sc], lambda p: (p["app"], p["stage"], p["label"], p["flavor"], p["variant"]))
        for (app_, stage_, label_, flavor_, variant_), pp in aggk.items():
            row = {"app": app_, "scenario": sc, "stage": stage_, "point": label_, "flavor": flavor_, "variant": variant_, "n": len(pp), "smoke": pp[0].get("smoke")}
            for name_, path_ in (("rps", "rps"), ("p50_ms", "lat_ms.med"), ("p99_ms", "lat_ms.p(99)"), ("cpu_cores", "res.cpu_cores"), ("cpu_user", "res.cpu_user_cores"),
                                 ("cpu_sys", "res.cpu_sys_cores"), ("cpu_ms_per_req", "cpu_ms_per_req"), ("mem_anon_max_mb", "res.mem_anon_max_mb"),
                                 ("mem_peak_mb", "res.mem_peak_mb"), ("threads_max", "res.threads_max"), ("queries_per_req", "queries_per_req")):
                st_ = stat([get(p, path_) for p in pp])
                if st_:
                    row.update({name_ + "_median": st_["med"], name_ + "_min": st_["min"], name_ + "_max": st_["max"], name_ + "_cv_pct": round(st_["cv"], 2)})
            csv_rows.setdefault("agg_summary", []).append(row)
        for p in main:
            if p["scenario"] == sc:
                csv_rows.setdefault("agg_points", []).append(
                    {"run": p["run_id"], "app": p["app"], "scenario": sc, "stage": p["stage"], "label": p["label"], "repeat": p["repeat"], "rps": round(p["rps"], 2),
                     "p50_ms": p["lat_ms"]["med"], "p99_ms": p["lat_ms"]["p(99)"], "err_rate": p["err_rate"], "cpu_cores": get(p, "res.cpu_cores"),
                     "cpu_user": get(p, "res.cpu_user_cores"), "cpu_sys": get(p, "res.cpu_sys_cores"), "cpu_ms_per_req": p["cpu_ms_per_req"],
                     "mem_peak_mb": get(p, "res.mem_peak_mb"), "mem_anon_max_mb": get(p, "res.mem_anon_max_mb"), "threads_max": get(p, "res.threads_max"), "fds_max": get(p, "res.fds_max"),
                     "queries_per_req": p["queries_per_req"], "flags": "|".join(p.get("flags", [])), "smoke": p.get("smoke")})
    return {"summary": summary, "points": main, "label": label}


def charts_load(main_info):
    pts = main_info.get("points", [])
    os.makedirs(CHARTS, exist_ok=True)
    made = []
    scen = sorted({p["scenario"] for p in pts}, key=lambda s: int(s[1:]))
    for sc in scen:
        A = group([p for p in pts if p["scenario"] == sc and p["stage"] == "A"], lambda p: (p["app"], int(p["params"]["VUS"])))
        series = {app: [(v, stat([p["rps"] for p in A[(app, v)]])["med"]) for (a, v) in sorted(A) if a == app] for app in APPS}
        f = svgchart.line_chart(os.path.join(CHARTS, "rps_vs_vu_%s.svg" % sc), "RPS vs konkurensi — %s" % SCEN_NAME[sc], "VU (closed-loop)", "RPS (median)", series, logx=True,
                                note=LABEL_LOAD + ("; smoke, bukan final" if main_info.get("label", "").startswith("smoke") else ""))
        made.append(f)
        B = group([p for p in pts if p["scenario"] == sc and p["stage"] == "B"], lambda p: (p["app"], p.get("frac")))
        series = {app: [(round(f_ * 100), stat([p["lat_ms"]["p(99)"] for p in B[(app, f_)]])["med"]) for (a, f_) in sorted(B, key=lambda k: (k[0], k[1] or 0)) if a == app and f_ is not None] for app in APPS}
        f = svgchart.line_chart(os.path.join(CHARTS, "latency_vs_rate_%s.svg" % sc), "p99 vs laju tetap — %s" % SCEN_NAME[sc], "laju (% dari saturasi yang lebih lambat)", "p99 ms (median)", series,
                                note=LABEL_LOAD)
        made.append(f)
    return [m for m in made if m]


def chart_timeseries(runs):
    """CPU dan memori vs waktu dari sampler.csv (S8 tahap B, ulangan pertama) untuk kedua app."""
    from runner import load_sampler
    os.makedirs(CHARTS, exist_ok=True)
    cpu, mem = {}, {}
    for r in runs:
        for rr in r["runs"]:
            if rr["scenario"] == "s8" and rr["stage"] in ("B", "SOAK") and rr.get("tag") in (None, "quiet") and rr["repeat"] == 0 and rr["app"] not in cpu:
                samp = load_sampler(os.path.join(RESULTS, rr["run_dir"]))
                rows = samp.get("app", [])
                if len(rows) < 5:
                    continue
                t0 = rows[0]["ts_ms"]
                cpu[rr["app"]] = [((b["ts_ms"] - t0) / 1000.0, (b["cpu_usage_us"] - a["cpu_usage_us"]) / 1e6 / max(1e-3, (b["ts_ms"] - a["ts_ms"]) / 1000.0)) for a, b in zip(rows, rows[1:])]
                mem[rr["app"]] = [((r_["ts_ms"] - t0) / 1000.0, r_["mem_current"] / 1048576.0) for r_ in rows]
    made = []
    if cpu:
        made.append(svgchart.line_chart(os.path.join(CHARTS, "cpu_vs_time_s8.svg"), "CPU aplikasi vs waktu — S8 tahap B (run 1)", "detik", "core terpakai", cpu, note=LABEL_LOAD))
        made.append(svgchart.line_chart(os.path.join(CHARTS, "mem_vs_time_s8.svg"), "Memori aplikasi vs waktu — S8 tahap B (run 1)", "detik", "memory.current (MB)", mem, note=LABEL_LOAD))
    return [m for m in made if m]


# ------------------------------------------------------------------ S10, S11
def section_soak_logcost(runs):
    pts = [p for r in runs if r["kind"] in ("bench", "smoke") for p in r["points"]]
    soak = [p for p in pts if p["scenario"] == "s10"]
    if soak:
        w("## S10 soak (S8 pada 70% saturasi)")
        w()
        w("Segmen berurutan tanpa restart; drift p99 dan pertumbuhan memori per segmen (median antar ulangan). **%s**" % LABEL_LOAD)
        w()
        rows = []
        for app in APPS:
            pp = [p for p in soak if p["app"] == app]
            segs = sorted({p["label"] for p in pp})
            if not segs:
                continue
            first, last = segs[0], segs[-1]
            f = stat([p["lat_ms"]["p(99)"] for p in pp if p["label"] == first])
            l = stat([p["lat_ms"]["p(99)"] for p in pp if p["label"] == last])
            mf = stat([get(p, "res.mem_anon_avg_mb") for p in pp if p["label"] == first])
            ml = stat([get(p, "res.mem_anon_avg_mb") for p in pp if p["label"] == last])
            tf = stat([get(p, "res.threads_max") for p in pp if p["label"] == last])
            rows.append([app, len(segs), cell(f, 2), cell(l, 2), cell(mf, 1), cell(ml, 1), cell(tf, 0)])
        md_table(["App", "Segmen", "p99 ms segmen pertama", "p99 ms segmen terakhir", "Mem anon MB awal", "Mem anon MB akhir", "Thread akhir"], rows)
    lc = [p for p in pts if p["scenario"] == "s11"]
    if lc:
        w("## S11 biaya logging (S8 pada laju tetap 50% saturasi: quiet vs access)")
        w()
        rows = []
        for app in APPS:
            q = [p for p in lc if p["app"] == app and p.get("s11_mode") == "quiet"]
            a = [p for p in lc if p["app"] == app and p.get("s11_mode") == "access"]
            if not q or not a:
                continue
            cq, ca = stat([p["cpu_ms_per_req"] for p in q]), stat([p["cpu_ms_per_req"] for p in a])
            pq, pa = stat([p["lat_ms"]["p(99)"] for p in q]), stat([p["lat_ms"]["p(99)"] for p in a])
            lines = [rr for r in runs for rr in r["runs"] if rr["scenario"] == "s11" and rr["app"] == app and rr.get("tag") == "access"]
            lpr = stat([x["log_lines_per_req"] for x in lines])
            bpr = stat([x["log_bytes_per_req"] for x in lines])
            rows.append([app, cell(cq, 3), cell(ca, 3), "%+.3f" % (ca["med"] - cq["med"]), cell(pq, 2), cell(pa, 2), "%+.2f" % (pa["med"] - pq["med"]), cell(lpr, 2), cell(bpr, 0)])
        md_table(["App", "CPU-ms/req quiet", "CPU-ms/req access", "Δ CPU-ms/req", "p99 quiet ms", "p99 access ms", "Δ p99 ms", "Baris log/req", "Byte log/req"], rows)
        w("Catatan: handler log Vapor pada mode access lebih ringkas daripada baris `loghttp` (ADR-004); selisih format dinyatakan, bukan disamarkan.")
        w()


# ------------------------------------------------------------------ build time
def build_stats(records, stack, config, scen, phase, key="wall_s"):
    return stat([r[key] for r in records if r["stack"] == stack and r["config"] == config and r["scenario"] == scen and r["phase"] == phase and r.get(key) is not None])


def section_build():
    d = latest_dir("build")
    if not d:
        w("## Build time (B1–B3)\n\nBelum dijalankan. `make build-bench` (butuh Go 1.27.2 dan Swift 6.4 native).\n")
        return {}
    recs = load_jsonl(os.path.join(d, "builds.jsonl"))
    meta = json.load(open(os.path.join(d, "meta.json"))) if os.path.exists(os.path.join(d, "meta.json")) else {}
    w("## Build time (B1–B3) — %s" % LABEL_NATIVE)
    w()
    ev = meta.get("verification", {})
    w("Run: `%s`. hw.ncpu=%s, %s, macOS %s. Ulangan: %s. Cache terisolasi (*.noindex), cache global tidak disentuh; paralelisme default toolchain (tanpa -j). Peak RSS = proses terbesar di pohon proses." % (
        os.path.basename(d), meta.get("hw_ncpu"), meta.get("hw_model"), meta.get("sw_vers"), meta.get("repeats")))
    w()
    w("Verifikasi toolchain: opsi SwiftPM `--scratch-path/--cache-path/--config-path/--security-path` diterima: **%s**; `--static-swift-stdlib` di macOS: **%s**; compilation caching SwiftPM aktif: **%s**." % (
        all(ev.get("swift_build_options_present", {}).get(k) for k in ("--scratch-path", "--cache-path", "--config-path", "--security-path")),
        "didukung" if get(ev, "static_swift_stdlib_on_macos.supported") else "TIDAK didukung (release native tanpa flag ini)", ev.get("compilation_caching_active")))
    w()
    rows = []
    matrix = {}
    for config in ("dev", "release"):
        for scen, phases in (("B1", ["download", "compile", "total"]), ("B2", ["build"]), ("B3", ["build"])):
            for phase in phases:
                for stack in APPS:
                    ws = build_stats(recs, stack, config, scen, phase)
                    if not ws:
                        continue
                    cpu = stat([r["user_s"] + r["sys_s"] for r in recs if r["stack"] == stack and r["config"] == config and r["scenario"] == scen and r["phase"] == phase])
                    rss = build_stats(recs, stack, config, scen, phase, "rss_bytes")
                    par = build_stats(recs, stack, config, scen, phase, "parallelism")
                    bsz = build_stats(recs, stack, config, scen, phase, "binary_bytes")
                    rows.append([scen, config, phase, stack, cell(ws, 2), cell(cpu, 1), cell(rss, 0, 1 / 1048576.0), cell(par, 2), ("%.1f" % (bsz["med"] / 1048576.0)) if bsz else "–"])
                    csv_rows.setdefault("agg_builds", []).append({"scenario": scen, "config": config, "phase": phase, "stack": stack, "wall_median": ws["med"], "wall_min": ws["min"],
                                                                  "wall_max": ws["max"], "cv": ws["cv"], "n": ws["n"]})
                    if (phase in ("total", "build")):
                        matrix[(scen, config, stack)] = ws
    md_table(["Skenario", "Konfigurasi", "Fase", "Stack", "Wall s", "CPU user+sys s", "Peak RSS MB", "Paralelisme efektif", "Binary MB"], rows)
    w("B1 dilaporkan sebagai total dan rincian unduh vs kompilasi; perbandingan utama memakai bagian kompilasi (unduhan bergantung jaringan).")
    w()
    return {"matrix": matrix, "meta": meta, "recs": recs}


def chart_builds(bi):
    if not bi:
        return []
    recs = bi["recs"]
    groups, vals = [], []
    for scen in ("B1", "B2", "B3"):
        for config in ("dev", "release"):
            row = []
            for stack in APPS:
                s = build_stats(recs, stack, config, scen, "total" if scen == "B1" else "build")
                row.append(s["med"] if s else None)
            if any(v is not None for v in row):
                groups.append("%s %s" % (scen, config))
                vals.append(row)
    os.makedirs(CHARTS, exist_ok=True)
    f = svgchart.bar_chart(os.path.join(CHARTS, "build_time.svg"), "Build time per skenario (median, %s)" % LABEL_NATIVE, "wall time (detik)", groups, APPS, vals, note="B1 = total unduh + kompilasi")
    return [f] if f else []


# ------------------------------------------------------------------ S12
def section_startup():
    d = latest_dir("startup")
    if not d:
        w("## S12 ukuran image dan startup\n\nBelum dijalankan: `make startup-bench`.\n")
        return {}
    imgs = json.load(open(os.path.join(d, "images.json")))
    rows = load_jsonl(os.path.join(d, "startup.jsonl"))
    w("## S12 ukuran image, startup, dan request pertama — %s" % LABEL_LOAD)
    w()
    w("Run: `%s`. **Waktu start mencakup overhead Docker yang sama untuk kedua stack** (create + start container + jaringan; diukur dari `Created` sampai /healthz 200 pertama dengan polling 10 ms dari container probe di jaringan yang sama, kedua cap waktu dari jam VM). Hanya selisih antar stack yang bermakna." % os.path.basename(d))
    w()
    irows = []
    for i in imgs["images"]:
        irows.append([i["image"], i["flavor"], "%.1f" % (i["image_bytes"] / 1048576.0), i["layers"], "%.1f" % (i["binary_bytes"] / 1048576.0), i["user"], i["arch"]])
    md_table(["Image", "Flavor", "Ukuran MB", "Layer", "Binary MB", "User", "Arch"], irows)
    for sk in imgs.get("skipped", []):
        w("- **Dilewati** %s/%s: %s" % (sk["app"], sk["flavor"], sk["reason"].replace("\n", " ")[:200]))
        warnings.append("S12: %s/%s tidak berhasil dibangun" % (sk["app"], sk["flavor"]))
    w()
    srows = []
    keys = sorted({(r["flavor"], r["app"]) for r in rows})
    for fl, app in keys:
        rr = [r for r in rows if r["flavor"] == fl and r["app"] == app]
        f = lambda k: stat([r["first_request_us"].get(k) / 1000.0 for r in rr if r["first_request_us"].get(k, -1) > 0])
        srows.append([fl, app, len(rr), cell(stat([r["startup_ms"] for r in rr]), 0), cell(f("S1"), 1), cell(f("S3"), 1), cell(f("S4"), 1), cell(f("S6"), 1),
                      cell(stat([r["mem_5s_anon_bytes"] for r in rr if r.get("mem_5s_anon_bytes") is not None]), 1, 1 / 1048576.0),
                      cell(stat([r["mem_after_100_anon_bytes"] for r in rr if r.get("mem_after_100_anon_bytes") is not None]), 1, 1 / 1048576.0),
                      cell(stat([r["mem_after_100_requests_bytes"] for r in rr]), 1, 1 / 1048576.0)])
        csv_rows.setdefault("agg_startup", []).append({"flavor": fl, "app": app, "n": len(rr), "startup_ms_median": stat([r["startup_ms"] for r in rr])["med"]})
    md_table(["Flavor", "App", "n", "Start ms (create→/healthz 200)", "Req pertama S1 ms", "S3 ms", "S4 ms", "S6 ms", "Mem anon 5 dtk setelah siap MB", "Mem anon setelah 100 req MB", "memory.current setelah 100 req MB (termasuk page cache)"], srows)
    return {"images": imgs, "rows": rows}


# ------------------------------------------------------------------ S13 tuned dan pool
def section_tuned(runs, main_info):
    tuned_runs = [r for r in runs if r["kind"] == "tuned"]
    if not tuned_runs:
        w("## S13 varian tuned dan sapuan pool\n\nBelum dijalankan: `make bench-tuned`. Perubahan yang direncanakan ada di `tuning/variants.yaml`.\n")
        return
    w("## S13 varian tuned (dilaporkan TERPISAH; kesimpulan utama hanya dari default)")
    w()
    w("**%s.** Perubahan, alasan, sumber dokumentasi, dan bukti verifikasi: `tuning/variants.yaml`. Laju tahap B tuned = laju default (resource sebanding)." % LABEL_LOAD)
    w()
    tp = [p for r in tuned_runs for p in r["points"] if p["variant"] == "tuned"]
    dp = [p for p in main_info.get("points", [])]
    rows = []
    for sc in sorted({p["scenario"] for p in tp}, key=lambda s: int(s[1:])):
        for app in APPS:
            def sat(pp, stage="A"):
                by = group([p for p in pp if p["scenario"] == sc and p["app"] == app and p["stage"] == stage], lambda p: p["repeat"])
                from runner import saturation_of
                return stat([saturation_of(v, 250.0)[0] for v in by.values()]) if by else None
            sd, st = sat(dp), sat(tp)
            def B(pp, k):
                return stat([get(p, k) if "." in k else p.get(k) for p in pp if p["scenario"] == sc and p["app"] == app and p["stage"] == "B" and p.get("frac") == 0.5])

            def rate_of(pp):
                v = [p["params"].get("RATE") for p in pp if p["scenario"] == sc and p["app"] == app and p["stage"] == "B" and p.get("frac") == 0.5]
                return float(v[0]) if v else None
            rd, rt = rate_of(dp), rate_of(tp)
            same_rate = bool(rd and rt and abs(rd - rt) / rd <= 0.02)
            for name, getter, needs_same in (("saturasi RPS (A)", lambda pp: sat(pp), False), ("p99 ms @50% (B)", lambda pp: B(pp, "lat_ms.p(99)"), True),
                                             ("CPU-ms/req @50% (B)", lambda pp: B(pp, "cpu_ms_per_req"), True), ("mem anon maks MB @50% (B)", lambda pp: B(pp, "res.mem_anon_max_mb"), True)):
                a, b = getter(dp), getter(tp)
                if a and b and needs_same and not same_rate:
                    rows.append([sc.upper(), app, name, cell(a, 2), cell(b, 2), "laju B berbeda (default %s vs tuned %s RPS): tidak sebanding" % (rd, rt)])
                elif a and b:
                    rows.append([sc.upper(), app, name, cell(a, 2), cell(b, 2), "%+.1f%%" % ((b["med"] - a["med"]) / a["med"] * 100.0) if a["med"] else "–"])
    if rows:
        md_table(["Skenario", "App", "Metrik", "Default", "Tuned", "Selisih median"], rows)
    else:
        w("Data default untuk perbandingan belum ada (jalankan `make bench-core` agar default tersedia).\n")
    sweep = [p for r in tuned_runs for p in r["points"] if (p.get("tag") or "").startswith("pool")]
    if sweep:
        w("### Sapuan ukuran pool koneksi total (default; sama untuk kedua stack; tahap A)")
        w()
        rows = []
        for sc in sorted({p["scenario"] for p in sweep}):
            for app in APPS:
                for pool in sorted({p["pool_total"] for p in sweep}):
                    pp = [p for p in sweep if p["scenario"] == sc and p["app"] == app and p["pool_total"] == pool]
                    if not pp:
                        continue
                    best = group(pp, lambda p: p["repeat"])
                    mx = stat([max(v, key=lambda p: p["rps"])["rps"] for v in best.values()])
                    p99 = stat([max(v, key=lambda p: p["rps"])["lat_ms"]["p(99)"] for v in best.values()])
                    rows.append([sc.upper(), app, pool, cell(mx, 0), cell(p99, 1), cell(stat([get(p, "res.cpu_cores") for p in pp]), 2)])
        md_table(["Skenario", "App", "Pool total", "RPS puncak (median)", "p99 ms pada RPS puncak", "CPU core"], rows)


# ------------------------------------------------------------------ skalabilitas
def section_scale(runs):
    sc_runs = [r for r in runs if r["kind"] == "scale"]
    res = {}
    if not sc_runs:
        w("## S14 skala vertikal (SC1)\n\nBelum dijalankan: `make scale-bench`.\n")
        return res
    w("## S14 skala vertikal (SC1) — kesimpulan hanya untuk 1 sampai 3 core")
    w()
    w("**%s.** Postgres tetap 2 CPU; run ditandai *terbatas DB* bila CPU Postgres ≥ 90%% dari alokasinya." % LABEL_LOAD)
    w()
    from runner import saturation_of
    pts = [p for r in sc_runs for p in r["points"]]
    rows = []
    for sc in ("s3", "s8"):
        for app in APPS:
            per = {}
            for n in sorted({p["app_cpus"] for p in pts}):
                by = group([p for p in pts if p["scenario"] == sc and p["app"] == app and p["app_cpus"] == n], lambda p: p["repeat"])
                per[n] = {r: (saturation_of(v, 250.0)[0], any("db_bound" in p["flags"] for p in v if p["rps"] >= 0.9 * max(q["rps"] for q in v)),
                              any("app_not_saturated" in p["flags"] for p in v if p["rps"] >= 0.9 * max(q["rps"] for q in v))) for r, v in by.items()}
            if 1 not in per:
                continue
            for n in sorted(per):
                effs = [per[n][r][0] / (n * per[1][r][0]) for r in per[n] if r in per[1] and per[1][r][0]]
                rps = stat([v[0] for v in per[n].values()])
                dbb = any(v[1] for v in per[n].values())
                nsat = any(v[2] for v in per[n].values())
                note = "; ".join(x for x in ("terbatas DB" if dbb else "", "app < 85% batas CPU (pembatas lain: k6/DB/VM; efisiensi bukan sifat aplikasi)" if nsat else "") if x) or "–"
                rows.append([sc.upper(), app, n, cell(rps, 0), cell(stat(effs), 2), note])
                res[(sc, app, n)] = stat(effs)
    md_table(["Skenario", "App", "CPU", "RPS saturasi", "Efisiensi RPS(n)/(n×RPS(1))", "Catatan"], rows)
    return res


def section_sc2(main_info):
    pts = [p for p in main_info.get("points", []) if p["stage"] == "A"]
    res = {}
    if not pts:
        return res
    w("## SC2 skala konkurensi (turunan tahap A)")
    w()
    rows = []
    for sc in ("s3", "s8"):
        for app in APPS:
            mem_sl, th_sl, knees = [], [], []
            for rep, v in group([p for p in pts if p["scenario"] == sc and p["app"] == app], lambda p: p["repeat"]).items():
                v = sorted(v, key=lambda p: int(p["params"]["VUS"]))
                xs = [int(p["params"]["VUS"]) for p in v]
                if len(xs) < 2:
                    continue
                m = slope(xs, [get(p, "res.mem_anon_max_mb") for p in v])
                t = slope(xs, [get(p, "res.threads_max") for p in v])
                if m is not None:
                    mem_sl.append(m * 100)
                if t is not None:
                    th_sl.append(t)
                base = v[0]["lat_ms"]["p(99)"]
                knee = next((int(p["params"]["VUS"]) for p in v[1:] if base and p["lat_ms"]["p(99)"] >= 2 * base), None)
                knees.append(knee if knee is not None else float("nan"))
            sm, st_, sk = stat(mem_sl), stat(th_sl), stat([k for k in knees if k == k])
            if sm or st_:
                rows.append([sc.upper(), app, cell(sm, 2), cell(st_, 3), cell(sk, 0) if sk else "tidak terdeteksi"])
                res[(sc, app)] = {"mem": sm, "threads": st_, "knee": sk}
    md_table(["Skenario", "App", "Kemiringan mem anon maks per 100 VU (MB)", "Pertumbuhan thread per VU", "Titik lutut latensi (VU; p99 ≥ 2× p99 VU terendah)"], rows)
    return res


def section_modular():
    d = latest_dir("modular")
    if not d:
        w("## M1 / SC3 satu modul vs banyak modul\n\nBelum dijalankan: `make modular-bench`.\n")
        return {}
    recs = load_jsonl(os.path.join(d, "modular.jsonl"))
    w("## M1 / SC3 skala basis kode: satu modul (T1) vs banyak modul (T2) — %s" % LABEL_NATIVE)
    w()
    w("Run: `%s`. **Kode sintetis (~%s baris/modul): kurva menunjukkan biaya struktur, bukan kualitas arsitektur.** Konfigurasi dev, cache terisolasi, satu mesin (laptop)." % (
        os.path.basename(d), recs[0].get("leaf_loc") if recs else "?"))
    w()
    rows = []
    mods = sorted({r["n"] for r in recs})
    for stack in APPS:
        for kind in ("B3", "B2-leaf", "B2-core"):
            for topo in ("T1", "T2"):
                row = [stack, kind, topo]
                for n in mods:
                    s = stat([r["wall_s"] for r in recs if r["stack"] == stack and r["kind"] == kind and r["topology"] == topo and r["n"] == n])
                    row.append(cell(s, 2))
                rows.append(row)
    md_table(["Stack", "Build", "Topologi"] + ["N=%d (s)" % n for n in mods], rows)
    slopes = {}
    rows = []
    for stack in APPS:
        for kind in ("B3", "B2-leaf", "B2-core"):
            for topo in ("T1", "T2"):
                per_rep = []
                for rep in sorted({r["repeat"] for r in recs}):
                    pp = [r for r in recs if r["stack"] == stack and r["kind"] == kind and r["topology"] == topo and r["repeat"] == rep]
                    if len({r["n"] for r in pp}) >= 2:
                        per_rep.append(slope([r["n"] for r in pp], [r["wall_s"] for r in pp]))
                s = stat([x for x in per_rep if x is not None])
                if s:
                    slopes[(stack, kind, topo)] = s
                    rows.append([stack, kind, topo, cell(s, 3)])
                    csv_rows.setdefault("agg_modular", []).append({"stack": stack, "kind": kind, "topology": topo, "slope_s_per_module": s["med"], "n_reps": s["n"]})
    w("**Kemiringan waktu build (detik per modul tambahan, regresi linear atas N yang diuji)**")
    w()
    md_table(["Stack", "Build", "Topologi", "Kemiringan s/modul"], rows)
    return {"recs": recs, "slopes": slopes, "mods": mods}


# ------------------------------------------------------------------ DX
def section_dx():
    files = sorted(glob.glob(os.path.join(RAW, "dx", "dx_*.json")))
    if not files:
        w("## Developer Experience (DX1–DX5)\n\nBelum dijalankan: `make dx-bench`.\n")
        return {}
    d = json.load(open(files[-1]))
    recs = d["records"]
    w("## Developer Experience (DX1–DX5) — %s" % LABEL_NATIVE)
    w()
    w("Run: `%s`. DX terukur bukan keseluruhan DX; faktor tidak terukur ada di bagian Kesimpulan > Tidak diukur." % os.path.basename(files[-1]))
    w("Asumsi: %s. %s." % (d["meta"].get("assumption_dx2"), d["meta"].get("assumption_dx1")))
    w()
    R = lambda dx, stack, key: stat([r[key] for r in recs if r.get("dx") == dx and r.get("stack") == stack and key in r])
    w("**DX1 edit → siap** (build B2 dev + start proses native sampai /healthz 200)")
    w()
    md_table(["Stack", "Edit→siap s", "Build s", "Start s"], [[a, cell(R("DX1", a, "edit_to_ready_s"), 2), cell(R("DX1", a, "build_s"), 2), cell(R("DX1", a, "start_to_health_s"), 2)] for a in APPS])
    w("**DX2 waktu test suite paritas** (go test ./... vs swift test [Swift Testing])")
    w()
    chk = [r for r in recs if r.get("check") == "jumlah_kasus_sama"]
    md_table(["Stack", "Kasus", "Cache build kosong (s)", "Cache hangat (s)"], [[a, (R("DX2", a, "cases") or {}).get("med", "–"), cell(R("DX2", a, "cold_wall_s"), 2), cell(R("DX2", a, "warm_wall_s"), 2)] for a in APPS])
    if chk:
        w("Jumlah kasus sama di kedua suite: Go=%s, Swift=%s, daftar bersama=%s, himpunan ID identik: **%s**." % (chk[0]["go"], chk[0]["swift"], chk[0]["shared_list"], chk[0]["identical_id_sets"]))
        w()
    d3 = next((r for r in recs if r.get("dx") == "DX3"), None)
    if d3:
        w("**DX3 ukuran kode dan dependency**")
        w()
        md_table(["Stack", "Baris kode (prod)", "File (prod)", "Baris test", "File test", "Dependency langsung", "Dependency transitif", "Ukuran cache dependency (MB)"],
                 [["go", d3["go"]["loc_prod"], d3["go"]["files_prod"], d3["go"]["loc_tests"], d3["go"]["files_tests"], d3["go"]["deps_direct"],
                   "%d (graf modul) / %d (terhubung ke binary)" % (d3["go"]["deps_transitive_module_graph"], d3["go"]["deps_modules_linked_into_binary"]), "%.1f" % (d3["go"]["dep_cache_kb"] / 1024)],
                  ["swift", d3["swift"]["loc_prod"], d3["swift"]["files_prod"], d3["swift"]["loc_tests"], d3["swift"]["files_tests"], d3["swift"]["deps_direct"],
                   d3["swift"]["deps_transitive_packages"], "%.1f" % (d3["swift"]["dep_cache_kb"] / 1024)]])
    d4 = [r for r in recs if r.get("dx") == "DX4"]
    if d4:
        w("**DX4 diagnostik compiler** (kualitatif; keluaran apa adanya di `results/raw/dx/diagnostics/`; tanpa skor dan tanpa pemenang)")
        w()
        md_table(["Stack", "Mutasi", "Baris keluaran", "Menunjuk baris yang benar", "Pesan error pertama"],
                 [[r["stack"], r["mutation"], r["output_lines"], "ya" if r["points_to_correct_line"] else "tidak", "`" + re.sub(r"^.*?/src/", "", re.sub(r"\x1b\[[0-9;]*m", "", (r["first_error"] or "–"))).replace("|", "\\|")[:170] + "`"] for r in d4])
    w("**DX5 onboarding** (clone bersih → request pertama sukses)")
    w()
    rows = []
    for a in APPS:
        one = next((r for r in recs if r.get("dx") == "DX5" and r.get("stack") == a), None)
        if one:
            rows.append([a, one["commands"], "; ".join(one["command_list"]), one["prerequisite_count"] , ", ".join(one["prerequisites"]), cell(R("DX5", a, "b1_dev_s"), 1), cell(R("DX5", a, "start_to_health_s"), 2)])
    md_table(["Stack", "Jumlah perintah", "Perintah", "Prasyarat", "Daftar prasyarat", "B1 dev s", "Start s"], rows)
    return {"recs": recs, "R": R}


# ------------------------------------------------------------------ profil
def section_profile():
    found = sorted(glob.glob(os.path.join(RESULTS, "profiles", "*", "*", "top10.json")))
    if not found:
        w("## Profil (10 fungsi teratas)\n\nBelum dijalankan: `make profile APP=go SCENARIO=s8` dan `APP=swift`.\n")
        return
    w("## Profil — 10 fungsi teratas (**penjelasan, bukan perbandingan**; %s)" % LABEL_NATIVE)
    w()
    for f in found:
        d = json.load(open(f))
        w("### %s %s (%ds @ %s RPS; %s)" % (d["app"], d["scenario"], d["duration_s"], d["rate_rps"], d["rate_basis"]))
        w()
        w("Sumber: %s. Berkas mentah: `%s`. Laporan tidak menyimpulkan penyebab selisih; narasi hanya bila didukung langsung oleh data profil di bawah." % (d.get("top10_source"), os.path.relpath(os.path.dirname(f), ROOT)))
        w()
        if d["app"] == "go":
            md_table(["#", "flat", "flat%", "cum", "cum%", "fungsi"], [[i + 1, r["flat"], r["flat_pct"], r["cum"], r["cum_pct"], "`" + r["name"] + "`"] for i, r in enumerate(d["top10"])])
        else:
            w("**Daftar mentah** (semua thread, termasuk thread idle):")
            w()
            md_table(["#", "sampel (top of stack)", "fungsi", "image"], [[i + 1, r["samples"], "`" + r["name"][:110] + "`", r["image"]] for i, r in enumerate(d["top10"])])
            if d.get("top10_excluding_wait"):
                w("**Tanpa primitif tunggu thread idle** (disaring: `%s`):" % "`, `".join(d.get("wait_functions_filtered", [])))
                w()
                md_table(["#", "sampel (top of stack)", "fungsi", "image"], [[i + 1, r["samples"], "`" + r["name"][:110] + "`", r["image"]] for i, r in enumerate(d["top10_excluding_wait"])])
            if d.get("xctrace"):
                w("Trace Instruments (Time Profiler) tersimpan: `%s/timeprofiler.trace`." % os.path.relpath(os.path.dirname(f), ROOT))
                w()
        if d.get("svg_note"):
            w("_%s_" % d["svg_note"])
            w()


# ------------------------------------------------------------------ konfigurasi/versi/peringatan
def section_config(runs, contract):
    w("## Versi, konfigurasi, dan checksum seed")
    w()
    meta = next((r["meta"] for r in reversed(runs) if r["meta"]), {})
    gomod = open(os.path.join(ROOT, "go-app", "go.mod")).read()
    ver = lambda m: (re.search(re.escape(m) + r" (v[\w.\-]+)", gomod) or [None, "?"])[1]
    resolved = json.load(open(os.path.join(ROOT, "swift-app", "Package.resolved")))
    pins = {p["identity"]: p["state"].get("version", p["state"].get("revision", "")[:8]) for p in (resolved.get("pins") or [])}
    meta_sw = re.sub(r"\s+", " ", str(meta.get("sw_vers", ""))).replace("ProductName: macOS ProductVersion: ", "").replace(" BuildVersion: ", " (") + (")" if "BuildVersion" in str(meta.get("sw_vers", "")) else "")
    rows = [["Go", "1.27.2 (image golang:1.27.2; chi %s, gorm %s, driver/postgres %s, loglayer %s)" % (ver("go-chi/chi/v5"), ver("gorm.io/gorm"), ver("gorm.io/driver/postgres"), ver("go.loglayer.dev/v3"))],
            ["Swift", "6.4.0 (image swift:6.4-noble; Vapor %s, Fluent %s, fluent-postgres-driver %s)" % (pins.get("vapor"), pins.get("fluent"), pins.get("fluent-postgres-driver"))],
            ["k6", meta.get("k6_version", "k6 v2.3.0")], ["Postgres", meta.get("postgres_version", "18.6 (alpine, digest terkunci)")]]
    if meta:
        rows += [["Mac", "%s, macOS %s, %s core (%sP+%sE)" % (meta.get("mac_model"), meta_sw, meta.get("hw_ncpu"), meta.get("perf_cores"), meta.get("eff_cores"))],
                 ["Docker", "%s (%s); VM %s vCPU, %.2f GiB; cgroup v%s" % (meta.get("docker_version"), meta.get("docker_engine"), meta.get("docker_vm_cpus"), int(meta.get("docker_vm_mem_bytes", 0)) / 2 ** 30, meta.get("cgroup_version"))],
                 ["Profil / flavor / varian", "%s / %s / %s; SLO p99 %s ms" % (meta.get("profile"), meta.get("image_flavor"), meta.get("variant"), meta.get("slo_p99_ms"))],
                 ["Batas", json.dumps(meta.get("limits"))], ["ulimit -n", meta.get("ulimit_n")]]
        for k, v in (meta.get("images") or {}).items():
            rows.append(["image " + k, "`%s`" % v])
        rows.append(["thermal sebelum", "CPU_Speed_Limit=%s" % get(meta, "thermal_before.cpu_speed_limit")])
    sums = (contract or {}).get("seed_checksums") or open(os.path.join(ROOT, "db", "checksums.txt")).read().strip().splitlines()
    rows.append(["Checksum seed (tabel, baris, md5)", "<br>".join("`%s`" % s for s in sums)])
    md_table(["Item", "Nilai"], rows)
    if contract:
        w("**Gerbang kesetaraan (make contract)**: %s; protokol: %s." % ("LULUS" if not contract.get("failures") else "GAGAL: %s" % contract["failures"], json.dumps(contract.get("protocol"))))
        w()


def section_warnings(runs, contract, bi):
    w("## Peringatan validitas")
    w()
    items = []
    if any(r["kind"] == "smoke" for r in runs):
        items.append("Ada run **smoke** (1 ulangan, durasi dipangkas): angka smoke diberi label 'smoke, bukan final' dan tidak dipakai untuk kesimpulan.")
    proto = (contract or {}).get("protocol") or {}
    if proto.get("swift", {}).get("kind") == "extended/unnamed" and proto.get("go", {}).get("kind", "").startswith("extended/named"):
        items.append("**Prepared statement tidak setara secara mekanis**: Go (GORM `PrepareStmt`) memakai statement bernama yang di-cache; Fluent/PostgresNIO memakai extended protocol dengan statement tanpa nama (parse per eksekusi) dan tidak mengekspos cache statement. Kedua sisi memakai extended protocol (bukti log Postgres, `make contract`); perbedaannya adalah perilaku default stack dan ikut terukur.")
    items.append("Fluent `with` tidak mendukung ORDER BY pada eager load; urutan (created_at DESC, id DESC) diterapkan di memori pada **kedua** sisi agar pekerjaan setara (S5).")
    items.append("GORM `SkipDefaultTransaction: true` dipakai agar jumlah query per request sama dengan Fluent (BEGIN/COMMIT tidak ditambahkan GORM pada satu statement).")
    items.append("Timestamp baris baru: Go mencetak presisi mikrodetik, Vapor `.iso8601` presisi detik; kontrak menormalkan timestamp dinamis (data fixture identik).")
    items.append("Build Linux Swift memakai `--build-system native` (deprecated) karena Swift Build default gagal link dengan `--static-swift-stdlib` di Swift 6.4 Linux; binary di-`strip` (setara `-s -w` Go). Lihat README > Deviasi.")
    items.append("Hanya pengukuran beban memakai container; build time, DX, modular, dan profil adalah **macOS native** dan tidak boleh dicampur dengan angka beban.")
    if bi and (bi.get("meta") or {}).get("release_swift_static_stdlib_used") is False:
        items.append("`--static-swift-stdlib` tidak didukung di macOS: build release Swift native tanpa flag itu.")
    flagc = {}
    for x in warnings:
        fl = x.rsplit(": ", 1)[-1]
        if fl == "app_not_saturated":
            continue
        flagc[fl] = flagc.get(fl, 0) + 1
    for fl, c in sorted(flagc.items()):
        items.append("%d titik ditandai `%s`" % (c, fl))
    for it in items:
        w("- " + it)
    w()
    w("Hasil tidak boleh dibandingkan dengan mesin lain. Perbedaan di bawah variasi antar ulangan (CV > 5% ditandai ⚠) tidak boleh dibaca sebagai selisih nyata.")
    w()


# ------------------------------------------------------------------ kesimpulan
def evaluate(metric, cond, ref, sa, sb, lower, det=False, d=2, scale=1.0, unit="", word="lebih baik"):
    """Kembalikan dict: kode (a|b|setara|belum), kalimat berformat baku yang menunjuk tabel sumber, dan baris matriks."""
    code, txt = judge(sa, sb, lower, deterministic=det, word=word)
    r = ratio(sa, sb) if (sa and sb and sa["med"] > 0 and sb["med"] > 0) else None  # rasio hanya bermakna untuk nilai positif
    go_c, sw_c = cell(sa, d, scale) + unit if sa else "–", cell(sb, d, scale) + unit if sb else "–"
    if sa and sb:
        sent = "%s (%s): Go %s, Swift %s, rasio Swift/Go %s → **%s** [%s]" % (metric, cond, go_c, sw_c, fmt_ratio(r), txt, ref)
    else:
        sent = "%s (%s): %s [%s]" % (metric, cond, txt, ref)
    return {"code": code, "sentence": sent, "row": [metric, cond, go_c, sw_c, fmt_ratio(r), txt]}


def section_conclusion(bi, st, dx, sc2, scale, mod, main_info):
    w("## Kesimpulan DX dan skalabilitas")
    w()
    w("Aturan: satu stack dinyatakan lebih baik hanya bila rentang min–maks kedua stack tidak tumpang tindih dan selisih median > 5%; selain itu 'setara' atau 'belum cukup bukti' (ulangan < 2). Setiap kalimat menunjuk tabel/metrik sumbernya. DX4 tidak diberi skor.")
    w()
    items = []   # (kelompok, hasil evaluate)

    def add(group, *a, **k):
        items.append((group, evaluate(*a, **k)))

    matrix = (bi or {}).get("matrix", {})
    for scen in ("B1", "B2", "B3"):
        for config in ("dev", "release"):
            a, b = matrix.get((scen, config, "go")), matrix.get((scen, config, "swift"))
            if a or b:
                add("DX", "Build %s %s" % (scen, config), "wall s, " + LABEL_NATIVE, "tabel Build time", a, b, True)
    if dx:
        R = dx["R"]
        add("DX", "DX1 edit→siap", "detik, " + LABEL_NATIVE, "tabel DX1", R("DX1", "go", "edit_to_ready_s"), R("DX1", "swift", "edit_to_ready_s"), True)
        add("DX", "DX2 test suite (cache build kosong)", "detik", "tabel DX2", R("DX2", "go", "cold_wall_s"), R("DX2", "swift", "cold_wall_s"), True)
        add("DX", "DX2 test suite (cache hangat)", "detik", "tabel DX2", R("DX2", "go", "warm_wall_s"), R("DX2", "swift", "warm_wall_s"), True)
        d3 = next((r for r in dx["recs"] if r.get("dx") == "DX3"), None)
        if d3:
            add("DX", "DX3 baris kode produksi (deskriptif)", "deterministik", "tabel DX3", stat([d3["go"]["loc_prod"]]), stat([d3["swift"]["loc_prod"]]), True, det=True, d=0, word="lebih sedikit")
            add("DX", "DX3 dependency transitif (deskriptif)", "Go: graf modul; Swift: Package.resolved", "tabel DX3", stat([d3["go"]["deps_transitive_module_graph"]]),
                stat([d3["swift"]["deps_transitive_packages"]]), True, det=True, d=0, word="lebih sedikit")
        add("DX", "DX5 onboarding (B1 dev)", "detik", "tabel DX5", R("DX5", "go", "b1_dev_s"), R("DX5", "swift", "b1_dev_s"), True, d=1)
    if st:
        rows = st["rows"]
        g = stat([r["startup_ms"] for r in rows if r["app"] == "go" and r["flavor"] == "distroless"])
        s_ = stat([r["startup_ms"] for r in rows if r["app"] == "swift" and r["flavor"] == "distroless"])
        add("DX", "Waktu start (distroless)", "ms; termasuk overhead Docker yang sama", "tabel S12", g, s_, True, d=0)
        im = {(i["image"].split(":")[0], i["flavor"]): i for i in st["images"]["images"]}
        a, b = im.get(("bench-go", "distroless")), im.get(("bench-swift", "distroless"))
        if a and b:
            add("DX", "Ukuran image (distroless; deskriptif)", "MB, deterministik", "tabel S12", stat([a["image_bytes"]]), stat([b["image_bytes"]]), True, det=True, d=1, scale=1 / 1048576.0, word="lebih kecil")
    for sc in ("s3", "s8"):
        for n in (2, 3):
            a, b = (scale or {}).get((sc, "go", n)), (scale or {}).get((sc, "swift", n))
            if a or b:
                add("SK", "Efisiensi skala S14 %s pada %d core" % (sc.upper(), n), "RPS(n)/(n×RPS(1)); hanya 1–3 core", "tabel S14", a, b, False)
    for sc in ("s3", "s8"):
        a, b = (sc2 or {}).get((sc, "go")), (sc2 or {}).get((sc, "swift"))
        if a and b:
            add("SK", "Kemiringan memori anon maks per 100 VU %s" % sc.upper(), "MB per 100 VU", "tabel SC2", a["mem"], b["mem"], True)
    slopes = (mod or {}).get("slopes", {})
    for kind in ("B2-leaf", "B3"):
        for topo in ("T1", "T2"):
            a, b = slopes.get(("go", kind, topo)), slopes.get(("swift", kind, topo))
            if a or b:
                add("SK", "Kemiringan build %s topologi %s" % (kind, topo), "s per modul; kode sintetis", "tabel M1", a, b, True, d=3)

    decided = [(g, e) for g, e in items if e["code"] in ("a", "b")]
    smoke_only = main_info.get("label", "").startswith("smoke")
    w("### Ringkasan")
    w()
    dx_txt = "; ".join(e["sentence"] for g, e in decided if g == "DX")
    sk_txt = "; ".join(e["sentence"] for g, e in decided if g == "SK")
    w("**DX.** " + (dx_txt or "Belum ada temuan DX yang lolos aturan (rentang tidak tumpang tindih dan selisih median > 5%). Metrik DX lain 'setara' atau 'belum cukup bukti' (lihat matriks)."))
    w()
    w("**Skalabilitas.** " + (sk_txt or "Belum ada temuan skalabilitas yang lolos aturan (lihat matriks)."))
    w()
    if smoke_only:
        w("_Catatan: data beban saat ini hanya smoke (1 ulangan); kesimpulan beban belum dapat ditarik._")
        w()
    w("### Matriks kriteria")
    w()
    md_table(["Metrik", "Kondisi", "Go (median [rentang])", "Swift (median [rentang])", "Rasio Swift/Go [rentang]", "Hasil"], [e["row"] for _, e in items])
    w("### Rekomendasi arsitektur kondisional (monorepo satu modul vs banyak modul)")
    w()
    recs = (mod or {}).get("recs", [])
    got_any = False
    for stack in APPS:
        for n in (mod or {}).get("mods", []):
            for kind in ("B2-leaf", "B3", "B2-core"):
                t1 = stat([r["wall_s"] for r in recs if r["stack"] == stack and r["kind"] == kind and r["topology"] == "T1" and r["n"] == n])
                t2 = stat([r["wall_s"] for r in recs if r["stack"] == stack and r["kind"] == kind and r["topology"] == "T2" and r["n"] == n])
                code, txt = judge(t1, t2, True, name_a="T1", name_b="T2")
                if code in ("a", "b"):
                    got_any = True
                    w("- Untuk stack **%s** pada **N=%d modul**, %s membangun %s lebih cepat dibanding %s (median T1 %.2fs vs T2 %.2fs; rasio T2/T1 %s; rentang tidak tumpang tindih) [tabel M1]. Berlaku hanya untuk N yang diuji, konfigurasi dev, kode sintetis." % (
                        stack, n, "T1" if code == "a" else "T2", kind, "T2" if code == "a" else "T1", t1["med"], t2["med"], fmt_ratio(ratio(t1, t2))))
    if not got_any:
        w("Belum ada rekomendasi yang didukung data (rentang tumpang tindih, selisih ≤ 5%, atau ulangan < 2 pada rentang N yang diuji).")
    w()
    w("### Tidak diukur (tanpa bobot; tidak dicampur dengan temuan terukur)")
    w()
    for t in ("**Kematangan ekosistem dan library** — dari pengetahuan umum: ekosistem Go untuk layanan web/ORM jauh lebih luas; Vapor/Fluent lebih kecil. Tidak diukur di sini.",
              "**Dukungan IDE dan debugging** — dari pengetahuan umum; tidak diukur.",
              "**Ketersediaan engineer** — dari pengetahuan umum; tidak diukur.",
              "**Stabilitas rilis** — transisi Vapor 4 ke 5 (Vapor 5 Beta 1, 15 September 2026; WebSocket dan kompresi belum ada; tidak disarankan produksi) bersumber dari [Vapor blog](https://blog.vapor.codes/posts/vapor-5-beta/) sebagaimana dikutip di `docs/PRD.md`; tidak diukur."):
        w("- " + t)
    w()
    w("### Batas kesimpulan")
    w()
    w("- Hasil berlaku untuk MacBook Pro M2 Pro (satu mesin, laptop), versi yang dikunci, VM Docker OrbStack (beban) dan macOS native (build/DX/modular/profil).")
    w("- Skala vertikal hanya untuk 1–3 core; M1 memakai kode sintetis dan hanya rentang N yang diuji (default 1, 5, 20); S14 bisa terbatas DB (ditandai).")
    w("- Penyebab selisih tidak disimpulkan tanpa dukungan profil (bagian Profil) atau dokumentasi yang dikutip.")
    w()


# ------------------------------------------------------------------ main
def write_csvs():
    for name, rows in csv_rows.items():
        if not rows:
            continue
        keys = sorted({k for r in rows for k in r})
        with open(os.path.join(RESULTS, name + ".csv"), "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=keys)
            wr.writeheader()
            wr.writerows(rows)


def main():
    runs = load_load_runs()
    contract_p = os.path.join(RAW, "contract", "summary.json")
    contract = json.load(open(contract_p)) if os.path.exists(contract_p) else None
    os.makedirs(RESULTS, exist_ok=True)
    w("# Laporan benchmark Go vs Swift")
    w()
    w("_Dibuat %s oleh `tools/report/report.py`. Semua angka berasal dari run nyata di `results/raw/`._" % time.strftime("%Y-%m-%d %H:%M:%S"))
    w()
    w("> **Label.** Angka beban: **%s**. Angka build time, DX, modular, dan profil: **%s**. Hasil tidak boleh dibandingkan dengan mesin lain." % (LABEL_LOAD, LABEL_NATIVE))
    w()
    body_start = len(out)
    section_config(runs, contract)
    cfg_end = len(out)
    main_info = section_load(runs) or {}
    section_soak_logcost(runs)
    bi = section_build()
    st = section_startup()
    section_tuned(runs, main_info)
    scale = section_scale(runs)
    sc2 = section_sc2(main_info)
    mod = section_modular()
    dx = section_dx()
    section_profile()
    # peringatan disisipkan setelah konfigurasi (dihitung setelah semua bagian terkumpul)
    saved = out[:]
    del out[:]
    section_warnings(runs, contract, bi)
    warn_block = out[:]
    del out[:]
    out.extend(saved[:cfg_end] + warn_block + saved[cfg_end:])
    section_conclusion(bi, st, dx, sc2, scale, mod, main_info)
    charts = []
    try:
        charts += charts_load(main_info)
        charts += chart_timeseries(runs)
        charts += chart_builds(bi)
    except Exception as e:  # grafik tidak boleh menggagalkan laporan
        out.append("\n_Grafik gagal dibuat: %s_\n" % e)
    pngs = []
    for c in charts:
        p = svgchart.to_png(c)
        pngs.append(p or c)
    if pngs:
        w("## Grafik")
        w()
        for p in pngs:
            w("- `%s`" % os.path.relpath(p, ROOT))
        w()
        if not all(p.endswith(".png") for p in pngs):
            w("_Sebagian grafik hanya SVG: konversi PNG (qlmanage, macOS) tidak tersedia._")
    write_csvs()
    open(os.path.join(RESULTS, "report.md"), "w").write("\n".join(out) + "\n")
    print("results/report.md (%d baris), grafik: %d, CSV: %s" % (len(out), len(pngs), ", ".join(sorted(csv_rows))))


if __name__ == "__main__":
    main()
