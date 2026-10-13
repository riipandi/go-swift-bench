#!/usr/bin/env python3
"""Build time native macOS: B1 (bersih), B2 (ubah satu file), B3 (dependency ter-cache); dev dan release.

Cache terisolasi di direktori sementara berakhiran .noindex (GOCACHE/GOMODCACHE; SwiftPM --scratch-path/--cache-path/
--config-path/--security-path). Cache global pengguna TIDAK disentuh. Sumber disalin ke direktori sementara agar repo tidak
berubah saat B2 mengedit file. Paralelisme default toolchain (tanpa -j). Ukur dengan /usr/bin/time -l.

Pakai: buildtime.py b1|b2|b3|all   (BUILD_REPEATS, BUILD_CONFIG=dev|release|both)
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
from benchenv import ROOT, load_env, log, sh  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
DEFAULT_REPEATS = {"b1": 3, "b2": 5, "b3": 3}
# File handler yang setara dan literal yang diubah di B2
EDIT = {"go": ("go-app/internal/httpapi/httpapi.go", '"status": "ok"'),
        "swift": ("swift-app/Sources/HTTPAPI/HTTPAPI.swift", 'StatusBody(status: "ok")')}


def time_run(cmd, cwd, env):
    """Jalankan di bawah /usr/bin/time -l. Kembalikan wall/user/sys (detik), peak RSS (byte), stderr."""
    t0 = time.time()
    r = subprocess.run(["/usr/bin/time", "-l"] + cmd, cwd=cwd, env=env, capture_output=True, text=True)
    wall_ext = time.time() - t0
    if r.returncode != 0:
        raise RuntimeError("build GAGAL (run dibatalkan): %s\n%s" % (" ".join(cmd), (r.stdout + r.stderr)[-1500:]))
    m = re.search(r"([\d.]+)\s+real\s+([\d.]+)\s+user\s+([\d.]+)\s+sys", r.stderr)
    rss = re.search(r"(\d+)\s+maximum resident set size", r.stderr)
    if not m:
        raise RuntimeError("keluaran time -l tidak terbaca: " + r.stderr[-300:])
    wall, user, sysc = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return {"wall_s": wall, "user_s": user, "sys_s": sysc, "rss_bytes": int(rss.group(1)) if rss else None,
            "parallelism": (user + sysc) / wall if wall > 0 else None, "wall_ext_s": wall_ext}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pmset_wait(max_wait=300):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        r = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True)
        m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", r.stdout)
        if not m or int(m.group(1)) >= 100:
            return True
        time.sleep(10)
    return False


def thermal_limit():
    r = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True)
    m = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", r.stdout)
    return int(m.group(1)) if m else 100


def _ignore(directory, names):
    skip = {".build", ".swiftpm", "bin"}
    for n in names:
        if n == "server" and os.path.isfile(os.path.join(directory, n)):  # binary hasil build, bukan direktori cmd/server
            skip.add(n)
    return [n for n in names if n in skip]


class Workspace:
    """Direktori sementara .noindex: sumber salinan + cache terisolasi."""

    def __init__(self, tag, src_root=None):
        src_root = src_root or ROOT
        base = tempfile.gettempdir()
        self.root = tempfile.mkdtemp(prefix="bench-build-%s-" % tag, suffix=".noindex", dir=base)
        self.src = os.path.join(self.root, "src")
        for app in ("go-app", "swift-app"):
            shutil.copytree(os.path.join(src_root, app), os.path.join(self.src, app), ignore=_ignore)
        # suite paritas membaca contract-tests/parity-cases relatif terhadap pohon sumber
        shutil.copytree(os.path.join(src_root, "contract-tests", "parity-cases"), os.path.join(self.src, "contract-tests", "parity-cases"))
        self.out = os.path.join(self.root, "out")
        os.makedirs(self.out)

    def fresh_caches(self):
        for d in ("gocache", "gomod", "swift-scratch", "swift-cache", "swift-config", "swift-security"):
            p = os.path.join(self.root, d)
            if os.path.exists(p):
                subprocess.run(["chmod", "-R", "u+w", p], capture_output=True)
                shutil.rmtree(p, ignore_errors=True)
            os.makedirs(p)

    def go_env(self):
        e = dict(os.environ)
        e.update(GOCACHE=os.path.join(self.root, "gocache"), GOMODCACHE=os.path.join(self.root, "gomod"),
                 GOFLAGS="-modcacherw", GOTOOLCHAIN="local")
        return e

    def swift_paths(self):
        return ["--scratch-path", os.path.join(self.root, "swift-scratch"), "--cache-path", os.path.join(self.root, "swift-cache"),
                "--config-path", os.path.join(self.root, "swift-config"), "--security-path", os.path.join(self.root, "swift-security")]

    def cleanup(self):
        subprocess.run(["chmod", "-R", "u+w", self.root], capture_output=True)
        shutil.rmtree(self.root, ignore_errors=True)


def go_build_cmd(ws, config):
    out = os.path.join(ws.out, "go-%s" % config)
    cmd = ["go", "build"]
    if config == "release":
        cmd += ["-trimpath", "-ldflags=-s -w"]
    return cmd + ["-o", out, "./cmd/server"], out


def swift_build_cmd(ws, config, static_ok):
    cmd = ["swift", "build", "--product", "App"] + ws.swift_paths()
    if config == "release":
        cmd = ["swift", "build", "-c", "release", "--product", "App"] + ws.swift_paths()
        if static_ok:
            cmd += ["--static-swift-stdlib"]
    return cmd


def swift_binary(ws, config):
    cmd = ["swift", "build", "--show-bin-path"] + (["-c", "release"] if config == "release" else []) + ws.swift_paths()
    r = subprocess.run(cmd, cwd=os.path.join(ws.src, "swift-app"), capture_output=True, text=True)
    return os.path.join(r.stdout.strip().splitlines()[-1], "App")


def cwd_of(ws, stack):
    return os.path.join(ws.src, "go-app" if stack == "go" else "swift-app")


def build_once(ws, stack, config, static_ok, label_phase="build"):
    """Satu build terukur. Kembalikan (metrik, path_binary)."""
    if stack == "go":
        cmd, binpath = go_build_cmd(ws, config)
        m = time_run(cmd, cwd_of(ws, stack), ws.go_env())
    else:
        cmd = swift_build_cmd(ws, config, static_ok)
        m = time_run(cmd, cwd_of(ws, stack), dict(os.environ))
        binpath = swift_binary(ws, config)
    m["binary_bytes"] = os.path.getsize(binpath) if os.path.exists(binpath) else None
    m["binary_sha256"] = sha256(binpath) if os.path.exists(binpath) else None
    m["cmd"] = " ".join(cmd)
    return m, binpath


def combine(parts):
    return {"wall_s": sum(p["wall_s"] for p in parts), "user_s": sum(p["user_s"] for p in parts), "sys_s": sum(p["sys_s"] for p in parts),
            "rss_bytes": max((p["rss_bytes"] or 0) for p in parts),
            "parallelism": (sum(p["user_s"] + p["sys_s"] for p in parts)) / max(1e-9, sum(p["wall_s"] for p in parts))}


class Recorder:
    def __init__(self, out_dir):
        self.f = open(os.path.join(out_dir, "builds.jsonl"), "a")

    def add(self, rec):
        self.f.write(json.dumps(rec) + "\n")
        self.f.flush()
        log("  %-5s %-7s %-3s r%d %-9s wall=%7.2fs user=%7.2fs sys=%6.2fs par=%.2f rss=%dMB bin=%s" % (
            rec["stack"], rec["config"], rec["scenario"], rec["repeat"], rec["phase"], rec["wall_s"], rec["user_s"], rec["sys_s"],
            rec["parallelism"] or 0, (rec["rss_bytes"] or 0) // 1048576, ("%.1fMB" % (rec["binary_bytes"] / 1048576)) if rec.get("binary_bytes") else "-"))


def b1(ws, stack, config, r, rec, static_ok):
    ws.fresh_caches()
    meta = dict(stack=stack, config=config, scenario="B1", repeat=r)
    if stack == "go":
        dl = time_run(["go", "mod", "download"], cwd_of(ws, stack), ws.go_env())
    else:
        dl = time_run(["swift", "package", "resolve"] + ws.swift_paths(), cwd_of(ws, stack), dict(os.environ))
    rec.add(dict(meta, phase="download", **dl))
    comp, _ = build_once(ws, stack, config, static_ok)
    rec.add(dict(meta, phase="compile", **comp))
    tot = combine([dl, comp])
    tot.update(binary_bytes=comp["binary_bytes"], binary_sha256=comp["binary_sha256"])
    rec.add(dict(meta, phase="total", **tot))


def warm(ws, stack, config, static_ok):
    """Cache hangat: unduh dependency dan build sekali (tidak diukur)."""
    ws.fresh_caches()
    if stack == "go":
        subprocess.run(["go", "mod", "download"], cwd=cwd_of(ws, stack), env=ws.go_env(), check=True)
    else:
        subprocess.run(["swift", "package", "resolve"] + ws.swift_paths(), cwd=cwd_of(ws, stack), check=True, capture_output=True)
    m, binpath = build_once(ws, stack, config, static_ok)
    return binpath


def edit_file(ws, stack, suffix):
    rel, literal = EDIT[stack]
    path = os.path.join(ws.src, rel)
    orig = open(path).read()
    if literal not in orig:
        raise RuntimeError("literal B2 tidak ditemukan di %s" % rel)
    new_literal = literal.replace('"ok"', '"ok-%s"' % suffix)
    open(path, "w").write(orig.replace(literal, new_literal, 1))
    return path, orig


def b2(ws, stack, config, repeats, rec, static_ok):
    binpath = warm(ws, stack, config, static_ok)
    prev_hash = sha256(binpath)
    for r in range(repeats):
        path, orig = edit_file(ws, stack, "b2-%d-%d" % (r, int(time.time())))
        try:
            pmset_wait()
            m, binpath = build_once(ws, stack, config, static_ok)
        finally:
            open(path, "w").write(orig)  # kembalikan file
        if m["binary_sha256"] == prev_hash:
            raise RuntimeError("B2: hash binary TIDAK berubah (tidak ada kompilasi ulang): %s/%s" % (stack, config))
        m["hash_changed"] = True
        prev_hash = m["binary_sha256"]
        rec.add(dict(stack=stack, config=config, scenario="B2", repeat=r, phase="build", **m))


def b3(ws, stack, config, repeats, rec, static_ok):
    warm(ws, stack, config, static_ok)
    for r in range(repeats):
        # Go: go clean -cache (module cache dipertahankan); Swift: swift package clean (checkouts dipertahankan)
        if stack == "go":
            subprocess.run(["go", "clean", "-cache"], cwd=cwd_of(ws, stack), env=ws.go_env(), check=True)
        else:
            subprocess.run(["swift", "package", "clean"] + ws.swift_paths(), cwd=cwd_of(ws, stack), check=True, capture_output=True)
        pmset_wait()
        m, _ = build_once(ws, stack, config, static_ok)
        rec.add(dict(stack=stack, config=config, scenario="B3", repeat=r, phase="build", **m))


def verify_toolchain():
    """Bukti verifikasi (dicatat ke meta): opsi SwiftPM, --static-swift-stdlib di macOS, compilation caching tidak aktif."""
    ev = {}
    h = subprocess.run(["swift", "build", "--help"], capture_output=True, text=True).stdout
    ev["swift_build_options_present"] = {o: (o in h) for o in ("--scratch-path", "--cache-path", "--config-path", "--security-path", "--static-swift-stdlib")}
    ev["compilation_caching_flags_in_help"] = [l.strip() for l in h.splitlines() if re.search(r"compilation.cache|compile.cache", l, re.I)]
    ev["compilation_caching_active"] = False if not ev["compilation_caching_flags_in_help"] else "periksa flag"
    ev["swift_version"] = subprocess.run(["swift", "--version"], capture_output=True, text=True).stdout.strip().splitlines()[0]
    ev["go_version"] = subprocess.run(["go", "version"], capture_output=True, text=True).stdout.strip()
    # coba --static-swift-stdlib pada paket kecil di macOS
    tmp = tempfile.mkdtemp(suffix=".noindex")
    try:
        os.makedirs(os.path.join(tmp, "Sources", "t"))
        open(os.path.join(tmp, "Package.swift"), "w").write('// swift-tools-version:6.0\nimport PackageDescription\nlet package = Package(name: "t", targets: [.executableTarget(name: "t")])\n')
        open(os.path.join(tmp, "Sources", "t", "main.swift"), "w").write('print("hi")\n')
        r = subprocess.run(["swift", "build", "-c", "release", "--static-swift-stdlib", "--scratch-path", os.path.join(tmp, "s"),
                            "--cache-path", os.path.join(tmp, "c"), "--config-path", os.path.join(tmp, "cf"), "--security-path", os.path.join(tmp, "sec")],
                           cwd=tmp, capture_output=True, text=True)
        out_txt = r.stdout + r.stderr
        # exit 0 saja tidak cukup: macOS menerima flag tetapi compiler memperingatkan 'no longer supports statically linking'
        unsupported = "no longer supports statically linking" in out_txt
        ev["static_swift_stdlib_on_macos"] = {"supported": r.returncode == 0 and not unsupported, "flag_accepted_exit0": r.returncode == 0,
                                              "warning_no_longer_supports_static": unsupported, "output_tail": out_txt[-300:]}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return ev


def stop_bench_containers():
    r = subprocess.run(["docker", "ps", "--filter", "name=bench-", "--format", "{{.Names}}"], capture_output=True, text=True)
    names = r.stdout.split()
    if names:
        log("Menghentikan container benchmark agar tidak berebut CPU dengan build: %s" % " ".join(names))
        subprocess.run(["docker", "stop"] + names, capture_output=True)
    return names


def estimate(which, configs, reps):
    go_s = {"dev": 40, "release": 45}
    sw_s = {"dev": 200, "release": 330}
    total = 0
    for c in configs:
        if "b1" in which:
            total += reps["b1"] * (go_s[c] + sw_s[c] + 20)
        if "b2" in which:
            total += go_s[c] + sw_s[c] + reps["b2"] * (8 + 25)
        if "b3" in which:
            total += go_s[c] + sw_s[c] + reps["b3"] * (go_s[c] + sw_s[c])
    return total


def main():
    sc = sys.argv[1] if len(sys.argv) > 1 else "all"
    env = load_env()
    which = ["b1", "b2", "b3"] if sc == "all" else [sc]
    cfg = os.environ.get("BUILD_CONFIG", "both")
    configs = ["dev", "release"] if cfg == "both" else [cfg]
    br = os.environ.get("BUILD_REPEATS")
    reps = {k: (int(br) if br else v) for k, v in DEFAULT_REPEATS.items()}
    est = estimate(which, configs, reps)
    log("build-bench %s | config=%s | ulangan %s | hw.ncpu=%s" % ("+".join(which), cfg, reps, subprocess.run(["sysctl", "-n", "hw.ncpu"], capture_output=True, text=True).stdout.strip()))
    log("Estimasi durasi (kasar, bergantung jaringan untuk B1): ~%d menit" % max(1, est // 60))
    stop_bench_containers()
    ev = verify_toolchain()
    log("Verifikasi toolchain: %s" % json.dumps(ev))
    static_ok = bool(ev["static_swift_stdlib_on_macos"]["supported"])
    out_dir = os.path.join(RESULTS, "raw", "build", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir)
    rec = Recorder(out_dir)
    meta = {"label": "macOS native", "hw_ncpu": int(subprocess.run(["sysctl", "-n", "hw.ncpu"], capture_output=True, text=True).stdout),
            "hw_model": subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True).stdout.strip(),
            "sw_vers": subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True).stdout.strip(),
            "verification": ev, "repeats": reps, "configs": configs, "thermal_before": thermal_limit(),
            "release_swift_static_stdlib_used": static_ok, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "isolation": "GOCACHE/GOMODCACHE dan SwiftPM scratch/cache/config/security di direktori sementara *.noindex; cache global tidak disentuh",
            "rss_note": "peak RSS = proses terbesar di pohon proses (ru_maxrss dari /usr/bin/time -l)"}
    ws = Workspace("all")
    try:
        for step in which:
            for config in configs:
                reps_n = reps[step]
                log("== %s %s" % (step.upper(), config))
                for r in range(reps_n if step == "b1" else 1):
                    order = ["go", "swift"] if r % 2 == 0 else ["swift", "go"]
                    for stack in order:
                        pmset_wait()
                        if step == "b1":
                            b1(ws, stack, config, r, rec, static_ok)
                if step in ("b2", "b3"):
                    # B2/B3: warm sekali per stack, ulangan di dalam; urutan stack diselang-seling antar konfigurasi
                    stacks = ["go", "swift"] if configs.index(config) % 2 == 0 else ["swift", "go"]
                    for stack in stacks:
                        pmset_wait()
                        (b2 if step == "b2" else b3)(ws, stack, config, reps_n, rec, static_ok)
    finally:
        meta["thermal_after"] = thermal_limit()
        meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
        ws.cleanup()
    log("selesai: %s" % out_dir)


if __name__ == "__main__":
    main()
