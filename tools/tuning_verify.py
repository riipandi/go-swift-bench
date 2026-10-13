#!/usr/bin/env python3
"""Bukti verifikasi perubahan tuned (tuning/variants.yaml): menjalankan image default dan tuned, membaca nilai runtime nyata.
Keluaran: results/raw/tuning_evidence.json (dipakai saat menulis/memperbarui variants.yaml)."""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from benchenv import APP_CONTAINERS, APP_SERVICES, ROOT, db_sh, dc, load_env, log, sh, wait_http  # noqa: E402
from runner import probe, stop_apps  # noqa: E402


def go_runtime_via_dev():
    # port admin 6060 dipublish oleh docker-compose.dev.yml (hanya untuk verifikasi ini)
    with urllib.request.urlopen("http://127.0.0.1:6060/metrics/runtime", timeout=10) as r:
        return json.loads(r.read())


def run_variant(app, variant, env):
    e = dict(env, VARIANT=variant)
    stop_apps(e)
    db_sh(["reset"], env=e)
    dc(["--dev", "up", "-d", "--force-recreate", APP_SERVICES[app]], env=e)
    wait_http({"go": 8080, "swift": 8081}[app])
    time.sleep(1)


def main():
    env = load_env()
    ev = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    for variant in ("default", "tuned"):
        e = dict(env, VARIANT=variant)
        for app in ("go", "swift"):
            dc(["build", APP_SERVICES[app]], env=e)
    # --- Go: GOGC/GOMEMLIMIT/GOMAXPROCS nyata dari runtime/metrics
    for variant in ("default", "tuned"):
        run_variant("go", variant, env)
        m = go_runtime_via_dev()
        ev["go_" + variant] = {k: m.get(k) for k in ("/gc/gogc:percent", "/gc/gomemlimit:bytes", "gomaxprocs", "version")}
        ev["go_" + variant]["image"] = "bench-go:%s%s" % (env["IMAGE_FLAVOR"], "-tuned" if variant == "tuned" else "")
    # --- Go: PGO di binary (go version -m)
    for variant in ("default", "tuned"):
        img = "bench-go:%s%s" % (env["IMAGE_FLAVOR"], "-tuned" if variant == "tuned" else "")
        cname = "bench-extract-pgo-%s" % variant
        sh(["docker", "rm", "-f", cname], check=False)
        sh(["docker", "create", "--name", cname, img])
        path = os.path.join(ROOT, "results", "raw", ".pgo_%s" % variant)
        sh(["docker", "cp", cname + ":/server", path])
        sh(["docker", "rm", "-f", cname], check=False)
        r = subprocess.run(["go", "version", "-m", path], capture_output=True, text=True)
        os.remove(path)
        ev["go_binary_%s" % variant] = [l.strip() for l in r.stdout.splitlines() if re.search(r"-pgo|-trimpath|-ldflags|CGO_ENABLED", l)]
    ev["go_pgo_profile_file"] = {"path": "go-app/pgo/default.pgo", "exists": os.path.exists(os.path.join(ROOT, "go-app", "pgo", "default.pgo")),
                                 "bytes": os.path.getsize(os.path.join(ROOT, "go-app", "pgo", "default.pgo")) if os.path.exists(os.path.join(ROOT, "go-app", "pgo", "default.pgo")) else None,
                                 "source": "results/profiles/go/s8/cpu.pb.gz (make profile APP=go SCENARIO=s8)"}
    # --- Swift: event loop dan pool per loop dari log startup
    for variant in ("default", "tuned"):
        run_variant("swift", variant, env)
        out = sh(["docker", "logs", APP_CONTAINERS["swift"]]).stdout
        m = re.search(r"event_loops: (\d+)", out)
        p = re.search(r"pool_per_loop: (\d+)", out)
        t = re.search(r"db_pool_total: (\d+)", out)
        ev["swift_" + variant] = {"event_loops": int(m.group(1)) if m else None, "pool_per_loop": int(p.group(1)) if p else None,
                                  "db_pool_total": int(t.group(1)) if t else None, "startup_line": out.strip().splitlines()[0] if out.strip() else None}
    # --- Swift: flag compiler tersedia (help swiftc) dan dokumentasi
    r = sh(["docker", "run", "--rm", env["SWIFT_BUILD_IMAGE"], "sh", "-c",
            "swiftc -frontend -help-hidden 2>&1 | grep -iE 'cross-module-optimization|enable-cmo|-lto' | head -5; swiftc --version | head -1"])
    ev["swift_flag_help"] = r.stdout.strip().splitlines()
    ev["swift_flag_built_in_tuned_image"] = "bench-swift:%s-tuned" % env["IMAGE_FLAVOR"]
    ev["swift_tuned_build_args"] = "SWIFT_EXTRA_FLAGS=%s" % os.environ.get("TUNED_SWIFT_FLAGS", "-Xswiftc -cross-module-optimization")
    for url in ("https://github.com/swiftlang/swift/blob/main/docs/CrossModuleOptimization.md",
                "https://go.dev/doc/pgo", "https://go.dev/doc/gc-guide", "https://docs.vapor.codes/advanced/server/"):
        try:
            req = urllib.request.Request(url, method="HEAD")
            ev.setdefault("doc_urls", {})[url] = urllib.request.urlopen(req, timeout=20).status
        except Exception as ex:
            ev.setdefault("doc_urls", {})[url] = str(ex)
    stop_apps(env)
    dc(["--dev", "stop", "go-app", "swift-app"], env=env, check=False)
    path = os.path.join(ROOT, "results", "raw", "tuning_evidence.json")
    json.dump(ev, open(path, "w"), indent=1)
    log(json.dumps(ev, indent=1))


if __name__ == "__main__":
    main()
