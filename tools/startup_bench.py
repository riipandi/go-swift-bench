#!/usr/bin/env python3
"""S12: ukuran image/binary, waktu start sampai /healthz 200, latensi request pertama (S1,S3,S4,S6), memori idle.

Waktu start = (respons 200 pertama dari probe, jam VM) - (waktu pembuatan container dari Docker, jam VM). Kedua stack membawa
overhead Docker yang sama (create + start container + jaringan); hanya selisih antar stack yang bermakna.
10 ulangan per stack (STARTUP_REPEATS). Dijalankan untuk flavor distroless dan alpine bila keduanya berhasil dibangun.
"""
import datetime
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
from benchenv import APP_CONTAINERS, APP_SERVICES, container_info, db_sh, dc, load_env, log, sh  # noqa: E402
from runner import APP_URL, RESULTS, SAMPLER_IMAGE, ensure_infra, probe, stop_apps, update_infra_cpusets  # noqa: E402

BIN_PATH = {"go": "/server", "swift": "/App"}


def parse_rfc3339_ns(s):
    s = s.rstrip("Z")
    if "." in s:
        base, frac = s.split(".")
        frac = (frac + "000000000")[:9]
    else:
        base, frac = s, "000000000"
    dt = datetime.datetime.strptime(base, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return int(dt.timestamp()) * 10 ** 9 + int(frac)


def image_facts(env, app, flavor):
    tag = "bench-%s:%s" % (app, flavor)
    r = sh(["docker", "image", "inspect", tag])
    info = json.loads(r.stdout)[0]
    # ukuran binary di dalam image: salin dari container yang tidak dijalankan (image tidak punya shell)
    cname = "bench-extract-%s-%s" % (app, flavor)
    sh(["docker", "rm", "-f", cname], check=False)
    sh(["docker", "create", "--name", cname, tag])
    path = os.path.join(RESULTS, "raw", ".extract_%s_%s" % (app, flavor))
    sh(["docker", "cp", "%s:%s" % (cname, BIN_PATH[app]), path])
    size = os.path.getsize(path)
    os.remove(path)
    sh(["docker", "rm", "-f", cname], check=False)
    return {"image": tag, "flavor": flavor, "image_bytes": info["Size"], "layers": len(info["RootFS"]["Layers"]),
            "binary_bytes": size, "user": info["Config"]["User"], "arch": info["Architecture"], "id": info["Id"]}


def mem_current(cid):
    r = sh(["docker", "run", "--rm", "--cgroupns", "host", "--entrypoint", "cat", SAMPLER_IMAGE,
            "/sys/fs/cgroup/docker/%s/memory.current" % cid])
    return int(r.stdout.strip())


def one_start(env, app, flavor):
    stop_apps(env)
    db_sh(["reset"], env=env)
    url = APP_URL[app]
    wait = subprocess.Popen(["docker", "exec", "bench-probe", "/sampler", "probe", "wait", "--url", url + "/healthz",
                             "--interval", "10ms", "--timeout", "60s"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.5)  # probe sudah polling sebelum container dibuat
    dc(["up", "-d", "--force-recreate", APP_SERVICES[app]], env=env)
    out, err = wait.communicate(timeout=90)
    if wait.returncode != 0:
        raise RuntimeError("aplikasi tidak siap: %s" % err)
    ok = json.loads(out)
    info = container_info(APP_CONTAINERS[app])
    created_ns = parse_rfc3339_ns(info["Created"])
    started_ns = parse_rfc3339_ns(info["State"]["StartedAt"])
    first = json.loads(probe(["first", "--base", url]))  # S1, S3, S4, S6 berurutan, sebelum warm-up
    t_ready = ok["first_ok_ns"]
    # memori 5 detik setelah siap (VM clock via probe now)
    while int(probe(["now"])) < t_ready + 5 * 10 ** 9:
        time.sleep(0.05)
    mem5 = mem_current(info["Id"])
    burst = json.loads(probe(["burst", "--base", url, "--n", "100"]))
    time.sleep(0.5)
    mem100 = mem_current(info["Id"])
    return {"startup_ms": (ok["first_ok_ns"] - created_ns) / 1e6, "start_to_ok_ms": (ok["first_ok_ns"] - started_ns) / 1e6,
            "create_to_start_ms": (started_ns - created_ns) / 1e6, "poll_attempts": ok["attempts"],
            "first_request_us": {k[:-3]: v for k, v in first.items() if k.endswith("_us")},
            "first_request_status": {k[:-7]: v for k, v in first.items() if k.endswith("_status")},
            "mem_5s_after_ready_bytes": mem5, "mem_after_100_requests_bytes": mem100, "burst_bad": burst["bad"]}


def main():
    env = load_env()
    repeats = int(os.environ.get("STARTUP_REPEATS", "10"))
    flavors_req = [f for f in os.environ.get("STARTUP_FLAVORS", "distroless,alpine").split(",") if f]
    out_dir = os.path.join(RESULTS, "raw", "startup", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    log("S12 startup-bench | %d ulangan per stack | flavor: %s | hasil: %s" % (repeats, ",".join(flavors_req), out_dir))
    log("Estimasi durasi: ~%d menit (per ulangan ~15 detik)" % max(1, int(len(flavors_req) * 2 * repeats * 15 / 60)))
    ensure_infra(env)
    update_infra_cpusets(env)
    facts, rows, skipped = [], [], []
    for flavor in flavors_req:
        e = dict(env, IMAGE_FLAVOR=flavor)
        built = []
        for app in ("go", "swift"):
            try:
                dc(["build", APP_SERVICES[app]], env=e)
                facts.append(image_facts(e, app, flavor))
                built.append(app)
            except Exception as ex:
                skipped.append({"app": app, "flavor": flavor, "reason": str(ex)[-400:]})
                log("  [lewati] %s/%s gagal dibangun: %s" % (app, flavor, str(ex)[-200:].replace("\n", " ")))
        for app in built:
            log("== %s / %s" % (app, flavor))
            order = list(range(repeats))
            for i in order:
                r = one_start(e, app, flavor)
                r.update({"app": app, "flavor": flavor, "repeat": i})
                rows.append(r)
                log("  r%02d start=%.0fms first S1/S3/S4/S6 = %s ms mem5s=%.1fMB mem100=%.1fMB" % (
                    i, r["startup_ms"], "/".join("%.1f" % (r["first_request_us"].get(k, -1) / 1000) for k in ("S1", "S3", "S4", "S6")),
                    r["mem_5s_after_ready_bytes"] / 1048576, r["mem_after_100_requests_bytes"] / 1048576))
    stop_apps(env)
    json.dump({"images": facts, "skipped": skipped, "note": "waktu start mencakup overhead Docker yang sama untuk kedua stack",
               "image_note": "ukuran dari docker image inspect; binary disalin dari image",
               "env": {"profile": env["PROFILE"], "app_cpus": env["APP_CPUS"], "app_mem": env["APP_MEM"]}},
              open(os.path.join(out_dir, "images.json"), "w"), indent=1)
    with open(os.path.join(out_dir, "startup.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    log("selesai: %s" % out_dir)


if __name__ == "__main__":
    main()
