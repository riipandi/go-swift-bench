#!/usr/bin/env python3
"""M1 / SC3 (make modular-bench): kurva waktu build terhadap jumlah modul N, topologi T1 (satu module/paket) vs T2 (banyak).

Ukuran: B3 (dependency ter-cache, artefak dibuang), B2-leaf (ubah satu modul daun), B2-core (ubah modul inti).
Native macOS, konfigurasi dev, cache terisolasi (*.noindex). Kode sintetis: kurva menunjukkan BIAYA STRUKTUR, bukan kualitas arsitektur.
Tidak menyentuh kode aplikasi utama. MODULES (default 1,5,20; 50 opsional), BUILD_REPEATS (default 3).
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "buildtime"))
import buildtime as bt  # noqa: E402
import modgen  # noqa: E402
from benchenv import ROOT, log  # noqa: E402

RESULTS = os.path.join(ROOT, "results")


def swift_paths(ws, scratch):
    return ["--scratch-path", scratch, "--cache-path", os.path.join(ws.root, "swift-cache"),
            "--config-path", os.path.join(ws.root, "swift-config"), "--security-path", os.path.join(ws.root, "swift-security")]


class Project:
    def __init__(self, ws, stack, topo, n):
        self.ws, self.stack, self.topo, self.n = ws, stack, topo, n
        self.dest = os.path.join(ws.root, "proj-%s-%s-%d" % (stack, topo, n))
        self.info = modgen.generate(stack, topo, n, self.dest, ROOT)
        self.scratch = os.path.join(ws.root, "scratch-%s-%s-%d" % (stack, topo, n))
        self.out = os.path.join(ws.out, "synth-%s-%s-%d" % (stack, topo, n))

    def env(self):
        return self.ws.go_env() if self.stack == "go" else dict(os.environ)

    def build_cmd(self):
        if self.stack == "go":
            return [c.replace("{out}", self.out) for c in self.info["build"]]
        return self.info["build"] + swift_paths(self.ws, self.scratch)

    def binary(self):
        if self.stack == "go":
            return self.out
        r = subprocess.run(["swift", "build", "--show-bin-path"] + swift_paths(self.ws, self.scratch), cwd=self.info["cwd"], capture_output=True, text=True)
        return os.path.join(r.stdout.strip().splitlines()[-1], "App")

    def build(self):
        m = bt.time_run(self.build_cmd(), self.info["cwd"], self.env())
        b = self.binary()
        m["binary_sha256"] = bt.sha256(b) if os.path.exists(b) else None
        return m

    def warm(self):
        if self.stack == "go":
            subprocess.run(["go", "mod", "download"], cwd=self.info["cwd"], env=self.env(), check=True, capture_output=True)
        else:
            subprocess.run(["swift", "package", "resolve"] + swift_paths(self.ws, self.scratch), cwd=self.info["cwd"], check=True, capture_output=True)
        return self.build()

    def clean(self):
        if self.stack == "go":
            subprocess.run(["go", "clean", "-cache"], cwd=self.info["cwd"], env=self.env(), check=True)
        else:
            subprocess.run(["swift", "package", "clean"] + swift_paths(self.ws, self.scratch), cwd=self.info["cwd"], check=True, capture_output=True)

    def edit(self, which, k):
        path = self.info["leaf_file"] if which == "leaf" else self.info["core_file"]
        lit = self.info["leaf_literal"] if which == "leaf" else self.info["core_literal"]
        orig = open(path).read()
        assert lit in orig, "literal tidak ditemukan: %s" % path
        open(path, "w").write(orig.replace(lit, lit[:-1] + "-edit%d-%d" % (k, int(time.time())) + '"', 1))
        return path, orig


def measure(ws, stack, topo, n, reps, writer):
    p = Project(ws, stack, topo, n)
    base = {"stack": stack, "topology": topo, "n": n, "leaf_loc": p.info["leaf_loc"]}
    p.warm()
    prev = p.build()["binary_sha256"]
    for r in range(reps):  # B3: dependency ter-cache, artefak dibuang
        p.clean()
        bt.pmset_wait()
        m = p.build()
        writer(dict(base, kind="B3", repeat=r, **m))
    for kind in ("leaf", "core"):  # B2-leaf, B2-core
        for r in range(reps):
            path, orig = p.edit(kind, r)
            try:
                bt.pmset_wait()
                m = p.build()
            finally:
                open(path, "w").write(orig)
            m["hash_changed"] = m["binary_sha256"] != prev
            if not m["hash_changed"]:
                raise RuntimeError("B2-%s: hash binary tidak berubah (%s %s N=%d)" % (kind, stack, topo, n))
            prev = m["binary_sha256"]
            writer(dict(base, kind="B2-" + kind, repeat=r, **m))


def estimate(mods, reps):
    t = 0
    for n in mods:
        for topo in ("T1", "T2"):
            go = 4 + 0.5 * n
            sw = 25 + (7 if topo == "T1" else 11) * n
            builds = 1 + 1 + reps * 3  # warm + prev + B3/B2-leaf/B2-core
            t += builds * (go + sw) + 20
    return t


def main():
    mods = [int(x) for x in os.environ.get("MODULES", "1,5,20").split(",")]
    br = os.environ.get("BUILD_REPEATS")
    reps = int(br) if br else 3
    log("modular-bench | N=%s | T1/T2 | go+swift | ulangan %d | native macOS, dev" % (mods, reps))
    log("Estimasi durasi (kasar): ~%d menit. Kode sintetis ~100 baris/modul: kurva menunjukkan biaya struktur, bukan kualitas arsitektur." % max(1, estimate(mods, reps) // 60))
    bt.stop_bench_containers()
    out_dir = os.path.join(RESULTS, "raw", "modular", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir)
    f = open(os.path.join(out_dir, "modular.jsonl"), "a")

    def writer(rec):
        f.write(json.dumps(rec) + "\n")
        f.flush()
        log("  %-5s %s N=%-3d %-8s r%d wall=%7.2fs user=%7.2fs par=%.2f" % (rec["stack"], rec["topology"], rec["n"], rec["kind"], rec["repeat"],
                                                                         rec["wall_s"], rec["user_s"], rec["parallelism"]))

    ws = bt.Workspace("modular")
    meta = {"label": "macOS native", "modules": mods, "repeats": reps, "config": "dev", "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "synthetic": "kode sintetis ~100 baris per modul (model, validasi, handler); bukan kode produksi",
            "hw_ncpu": subprocess.run(["sysctl", "-n", "hw.ncpu"], capture_output=True, text=True).stdout.strip()}
    try:
        for stack in ("go", "swift"):
            ws.fresh_caches()  # cache bersama untuk semua proyek stack ini; dependency diunduh sekali (tidak diukur)
            for i, n in enumerate(mods):
                for topo in (("T1", "T2") if (i % 2 == 0) else ("T2", "T1")):
                    log("== %s %s N=%d" % (stack, topo, n))
                    measure(ws, stack, topo, n, reps, writer)
    finally:
        meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=1)
        ws.cleanup()
    log("selesai: %s" % out_dir)


if __name__ == "__main__":
    main()
