#!/usr/bin/env python3
"""DX1..DX5 (native macOS, cache terisolasi, tidak bersamaan dengan beban Docker).

DX1 edit -> siap: ubah satu file, build dev (B2), start proses native, ukur sampai /healthz 200.
DX2 waktu test suite paritas: go test ./... vs swift test (Swift Testing), cache build kosong dan hangat; jumlah kasus harus sama.
DX3 ukuran kode (baris non-kosong non-komentar), jumlah file, dependency langsung/transitif, ukuran cache dependency.
DX4 diagnostik compiler: tiga mutasi baku pada salinan sementara; keluaran compiler disimpan apa adanya (tanpa skor).
DX5 onboarding: clone bersih -> request pertama sukses: jumlah perintah, prasyarat, waktu (B1 dev + start native).
"""
import json
import os
import re
import subprocess
import sys
import time
import http.client as httpc

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))
sys.path.insert(0, os.path.join(HERE, "..", "buildtime"))
import buildtime as bt  # noqa: E402
from benchenv import ROOT, db_sh, dc, log  # noqa: E402

RESULTS = os.path.join(ROOT, "results")
PORTS = {"go": 8090, "swift": 8091}
DX_DIR = os.path.join(RESULTS, "raw", "dx")


def native_env(stack, ws=None):
    e = dict(ws.go_env() if (ws and stack == "go") else os.environ)
    e.update(DB_HOST="localhost", DB_PORT="54322", DB_USER="bench", DB_PASSWORD="bench", DB_NAME="bench", LOG_MODE="quiet",
             PORT=str(PORTS[stack]), ADMIN_PORT="6070", DB_POOL="16", EVENT_LOOPS="2")
    return e


def wait_health(port, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            c = httpc.HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/healthz")
            r = c.getresponse()
            r.read()
            c.close()
            if r.status == 200:
                return time.time()
        except Exception:
            pass
        time.sleep(0.01)
    raise RuntimeError("proses native tidak siap di port %d" % port)


def first_request(port):
    c = httpc.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request("GET", "/users/1")
    r = c.getresponse()
    r.read()
    return r.status


def start_proc(binpath, stack, env):
    p = subprocess.Popen([binpath], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p


def stop_proc(p):
    p.terminate()
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


# ------------------------------------------------------------------ DX1
def dx1(repeats):
    out = []
    for stack in ("go", "swift"):
        ws = bt.Workspace("dx1")
        try:
            bt.warm(ws, stack, "dev", False)
            for r in range(repeats):
                bt.pmset_wait()
                path, orig = bt.edit_file(ws, stack, "dx1-%d" % r)
                try:
                    t0 = time.time()
                    m, binpath = bt.build_once(ws, stack, "dev", False)
                    t_built = time.time()
                    p = start_proc(binpath, stack, native_env(stack, ws))
                    try:
                        t_ok = wait_health(PORTS[stack])
                    finally:
                        stop_proc(p)
                finally:
                    open(path, "w").write(orig)
                rec = {"dx": "DX1", "stack": stack, "repeat": r, "edit_to_ready_s": t_ok - t0, "build_s": m["wall_s"], "start_to_health_s": t_ok - t_built}
                out.append(rec)
                log("  DX1 %-5s r%d edit->siap=%.2fs (build %.2fs + start %.2fs)" % (stack, r, rec["edit_to_ready_s"], rec["build_s"], rec["start_to_health_s"]))
        finally:
            ws.cleanup()
    return out


# ------------------------------------------------------------------ DX2
def parity_ids(path):
    return sorted(set(l.strip() for l in open(path) if l.strip())) if os.path.exists(path) else []


def dx2(repeats):
    out, ids = [], {}
    for stack in ("go", "swift"):
        ws = bt.Workspace("dx2")
        rep = os.path.join(ws.root, "%s_cases.txt" % stack)
        try:
            ws.fresh_caches()
            if stack == "go":
                env = ws.go_env()
                env["PARITY_REPORT"] = rep
                subprocess.run(["go", "mod", "download"], cwd=bt.cwd_of(ws, stack), env=env, check=True)  # dependency tersedia (tak diukur)
                cmd = ["go", "test", "-count=1", "./..."]
                clean = lambda: subprocess.run(["go", "clean", "-cache"], cwd=bt.cwd_of(ws, stack), env=env, check=True)
            else:
                env = dict(os.environ, PARITY_REPORT=rep)
                subprocess.run(["swift", "package", "resolve"] + ws.swift_paths(), cwd=bt.cwd_of(ws, stack), check=True, capture_output=True)
                cmd = ["swift", "test"] + ws.swift_paths()
                clean = lambda: subprocess.run(["swift", "package", "clean"] + ws.swift_paths(), cwd=bt.cwd_of(ws, stack), check=True, capture_output=True)
            for r in range(repeats):
                clean()
                if os.path.exists(rep):
                    os.remove(rep)
                bt.pmset_wait()
                cold = bt.time_run(cmd, bt.cwd_of(ws, stack), env)
                ids[stack] = parity_ids(rep)
                warm = bt.time_run(cmd, bt.cwd_of(ws, stack), env)
                out.append({"dx": "DX2", "stack": stack, "repeat": r, "cold_wall_s": cold["wall_s"], "cold_cpu_s": cold["user_s"] + cold["sys_s"],
                            "warm_wall_s": warm["wall_s"], "warm_cpu_s": warm["user_s"] + warm["sys_s"], "cases": len(ids[stack]),
                            "framework": "testing (stdlib)" if stack == "go" else "Swift Testing"})
                log("  DX2 %-5s r%d cold=%.2fs warm=%.2fs kasus=%d" % (stack, r, cold["wall_s"], warm["wall_s"], len(ids[stack])))
        finally:
            ws.cleanup()
    shared = json.load(open(os.path.join(ROOT, "contract-tests", "parity-cases", "cases.json")))["cases"]
    same = ids.get("go") == ids.get("swift") == sorted(c["id"] for c in shared)
    out.append({"dx": "DX2", "check": "jumlah_kasus_sama", "go": len(ids.get("go", [])), "swift": len(ids.get("swift", [])),
                "shared_list": len(shared), "identical_id_sets": bool(same)})
    if not same:
        raise RuntimeError("DX2: kasus paritas Go %d != Swift %d != daftar bersama %d" % (len(ids.get("go", [])), len(ids.get("swift", [])), len(shared)))
    return out


# ------------------------------------------------------------------ DX3
def loc(path, lang):
    n = 0
    in_block = False
    for line in open(path, errors="replace"):
        s = line.strip()
        if not s:
            continue
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//"):
            continue
        n += 1
    return n


def walk(root, ext, test):
    files = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in (".build", ".swiftpm", "bin", "pgo")]
        for nm in names:
            if nm.endswith(ext):
                is_test = nm.endswith("_test.go") or "/Tests/" in (d + "/")
                if is_test == test:
                    files.append(os.path.join(d, nm))
    return files


def du_kb(path):
    return int(subprocess.run(["du", "-sk", path], capture_output=True, text=True).stdout.split()[0])


def dx3():
    res = {"dx": "DX3"}
    go_root, sw_root = os.path.join(ROOT, "go-app"), os.path.join(ROOT, "swift-app")
    for stack, root, ext in (("go", go_root, ".go"), ("swift", sw_root, ".swift")):
        prod, tests = walk(root, ext, False), walk(root, ext, True)
        res[stack] = {"loc_prod": sum(loc(f, stack) for f in prod), "files_prod": len(prod),
                      "loc_tests": sum(loc(f, stack) for f in tests), "files_tests": len(tests)}
    # dependency Go
    r = subprocess.run(["go", "list", "-m", "all"], cwd=go_root, capture_output=True, text=True)
    mods = [l for l in r.stdout.splitlines() if l.strip()][1:]
    gomod = open(os.path.join(go_root, "go.mod")).read()
    direct = [l for l in gomod.splitlines() if re.match(r"\s+\S+\s+v\S+\s*$", l) and "// indirect" not in l]
    linked = subprocess.run(["go", "list", "-deps", "-f", "{{with .Module}}{{.Path}}{{end}}", "./cmd/server"], cwd=go_root, capture_output=True, text=True)
    res["go"].update(deps_direct=len(direct), deps_transitive_module_graph=len(mods),
                     deps_modules_linked_into_binary=len(set(x for x in linked.stdout.split() if x)) - 1)
    # dependency Swift
    resolved = json.load(open(os.path.join(sw_root, "Package.resolved")))
    pins = resolved.get("pins") or resolved.get("object", {}).get("pins", [])
    direct_sw = len(re.findall(r"\.package\(url:", open(os.path.join(sw_root, "Package.swift")).read()))
    res["swift"].update(deps_direct=direct_sw, deps_transitive_packages=len(pins))
    # ukuran cache dependency (cache terisolasi baru, hanya unduh dependency)
    ws = bt.Workspace("dx3")
    try:
        ws.fresh_caches()
        subprocess.run(["go", "mod", "download"], cwd=bt.cwd_of(ws, "go"), env=ws.go_env(), check=True)
        subprocess.run(["swift", "package", "resolve"] + ws.swift_paths(), cwd=bt.cwd_of(ws, "swift"), check=True, capture_output=True)
        res["go"]["dep_cache_kb"] = du_kb(os.path.join(ws.root, "gomod"))
        res["swift"]["dep_cache_kb"] = du_kb(os.path.join(ws.root, "swift-cache")) + du_kb(os.path.join(ws.root, "swift-scratch"))
    finally:
        ws.cleanup()
    log("  DX3 %s" % json.dumps(res))
    return [res]


# ------------------------------------------------------------------ DX4
MUTATIONS = {
    "go": {"file": "go-app/internal/httpapi/httpapi.go",
           "anchor": 'writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})',
           "mut": {
               "type_mismatch": 'writeJSON(w, "ok", map[string]string{"status": "ok"})',
               "undefined_symbol": 'writeJSON(w, http.StatusOK, domain.NoSuchHelper())',
               "unhandled_error": 'b, err := json.Marshal(domain.NewBenchPayload())\n\t_ = b\n\twriteJSON(w, http.StatusOK, map[string]string{"status": "ok"})',
           }},
    "swift": {"file": "swift-app/Sources/HTTPAPI/HTTPAPI.swift",
              "anchor": 'try jsonResponse(StatusBody(status: "ok"))',
              "mut": {
                  "type_mismatch": 'try jsonResponse(StatusBody(status: 200))',
                  "undefined_symbol": 'try jsonResponse(noSuchHelper())',
                  "unhandled_error": 'jsonResponse(StatusBody(status: "ok"))',
              }},
}


def dx4():
    diag_dir = os.path.join(DX_DIR, "diagnostics")
    os.makedirs(diag_dir, exist_ok=True)
    out = []
    for stack in ("go", "swift"):
        ws = bt.Workspace("dx4")
        spec = MUTATIONS[stack]
        try:
            bt.warm(ws, stack, "dev", False)
            path = os.path.join(ws.src, spec["file"])
            orig = open(path).read()
            for name, repl in spec["mut"].items():
                if spec["anchor"] not in orig:
                    raise RuntimeError("anchor DX4 tidak ditemukan: %s" % spec["file"])
                mutated = orig.replace(spec["anchor"], repl, 1)
                line_no = orig[: orig.index(spec["anchor"])].count("\n") + 1
                open(path, "w").write(mutated)
                try:
                    if stack == "go":
                        cmd, env = ["go", "build", "-o", os.path.join(ws.out, "x"), "./cmd/server"], ws.go_env()
                    else:
                        cmd, env = ["swift", "build", "--product", "App"] + ws.swift_paths(), dict(os.environ)
                    r = subprocess.run(cmd, cwd=bt.cwd_of(ws, stack), env=env, capture_output=True, text=True)
                finally:
                    open(path, "w").write(orig)
                raw = r.stdout + r.stderr
                fn = os.path.join(diag_dir, "%s_%s.txt" % (stack, name))
                header = "# stack=%s mutasi=%s file=%s baris-dimutasi=%d exit=%d\n# perintah: %s\n# (keluaran compiler apa adanya di bawah)\n" % (
                    stack, name, spec["file"], line_no, r.returncode, " ".join(cmd))
                open(fn, "w").write(header + raw)
                base = os.path.basename(spec["file"])
                located = bool(re.search(re.escape(base) + r":%d(:|\b)" % line_no, raw))
                clean = re.sub(r"\x1b\[[0-9;]*m", "", raw)
                diag = [l for l in clean.splitlines() if re.search(r":\d+:\d+: ", l)]
                errs = [l for l in diag if "error:" in l] or [l for l in diag if "warning:" not in l] or diag
                out.append({"dx": "DX4", "stack": stack, "mutation": name, "exit": r.returncode, "output_lines": len(raw.splitlines()),
                            "points_to_correct_line": located, "mutated_line": line_no, "first_error": (re.sub(r"^.*?/(src/)?", "", errs[0])[:300] if errs else None),
                            "file": os.path.relpath(fn, ROOT)})
                log("  DX4 %-5s %-16s exit=%d baris-keluaran=%d lokasi-benar=%s" % (stack, name, r.returncode, len(raw.splitlines()), located))
        finally:
            ws.cleanup()
    return out


# ------------------------------------------------------------------ DX5
ONBOARD = {"go": ["make doctor", "make db-up", "make db-seed", "make go-run", "GET /users/1"],
           "swift": ["make doctor", "make db-up", "make db-seed", "make swift-run", "GET /users/1"]}
PREREQS = {"go": ["docker", "make", "git", "go"], "swift": ["docker", "make", "git", "swift (Xcode 27 / toolchain 6.4)"]}


def dx5(repeats):
    clone = os.path.join(bt.tempfile.mkdtemp(suffix=".noindex"), "clone")
    subprocess.run(["git", "clone", "--local", "--quiet", ROOT, clone], check=True)
    out = []
    try:
        for r in range(repeats):
            for stack in (("go", "swift") if r % 2 == 0 else ("swift", "go")):
                ws = bt.Workspace("dx5", src_root=clone)
                try:
                    ws.fresh_caches()
                    bt.pmset_wait()
                    t0 = time.time()
                    if stack == "go":
                        dl = bt.time_run(["go", "mod", "download"], bt.cwd_of(ws, stack), ws.go_env())
                    else:
                        dl = bt.time_run(["swift", "package", "resolve"] + ws.swift_paths(), bt.cwd_of(ws, stack), dict(os.environ))
                    comp, binpath = bt.build_once(ws, stack, "dev", False)
                    t_built = time.time()
                    p = start_proc(binpath, stack, native_env(stack, ws))
                    try:
                        t_ok = wait_health(PORTS[stack])
                        status = first_request(PORTS[stack])
                    finally:
                        stop_proc(p)
                    t_end = time.time()
                finally:
                    ws.cleanup()
                rec = {"dx": "DX5", "stack": stack, "repeat": r, "commands": len(ONBOARD[stack]), "command_list": ONBOARD[stack],
                       "prerequisites": PREREQS[stack], "prerequisite_count": len(PREREQS[stack]),
                       "b1_dev_s": dl["wall_s"] + comp["wall_s"], "start_to_health_s": t_ok - t_built, "first_request_status": status,
                       "total_s": t_end - t0}
                out.append(rec)
                log("  DX5 %-5s r%d B1 dev=%.1fs + start=%.2fs request-pertama=%d" % (stack, r, rec["b1_dev_s"], rec["start_to_health_s"], status))
    finally:
        import shutil
        shutil.rmtree(os.path.dirname(clone), ignore_errors=True)
    return out


def main():
    br = os.environ.get("BUILD_REPEATS")
    repeats = int(br) if br else 3
    os.makedirs(DX_DIR, exist_ok=True)
    log("dx-bench | ulangan %d | native macOS, cache terisolasi (*.noindex) | estimasi kasar: %d menit" % (repeats, 6 + repeats * 25))
    bt.stop_bench_containers()
    db_sh(["up"], env=None)  # hanya Postgres idle (diperlukan Go saat start; bukan beban)
    results = []
    meta = {"label": "macOS native", "repeats": repeats, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "assumption_dx2": "cold = cache build kosong, dependency sudah diunduh (agar jaringan tidak ikut terukur); warm = tanpa perubahan",
            "assumption_dx1": "Postgres idle berjalan; Go membuka koneksi DB saat start, Swift membuka koneksi lazy (perbedaan perilaku default stack)"}
    for name, fn in (("DX3", lambda: dx3()), ("DX4", lambda: dx4()), ("DX2", lambda: dx2(repeats)), ("DX1", lambda: dx1(repeats)), ("DX5", lambda: dx5(repeats))):
        log("== %s" % name)
        results += fn()
    meta["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    path = os.path.join(DX_DIR, "dx_%s.json" % time.strftime("%Y%m%d-%H%M%S"))
    json.dump({"meta": meta, "records": results}, open(path, "w"), indent=1)
    db_sh(["down"], env=None)
    log("selesai: %s" % path)


if __name__ == "__main__":
    main()
