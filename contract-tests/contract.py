#!/usr/bin/env python3
"""Gerbang kesetaraan (make contract). Gagal = benchmark berhenti.

1. Kontrak: status + bentuk JSON == golden (fixture) di kedua aplikasi, termasuk 400/404.
2. Jumlah query per request sama di tiap endpoint (pg_stat_statements).
3. Konfigurasi runtime (pool, thread/event loop, batas container) sesuai rencana; logging quiet 0 baris akses,
   access tepat satu baris per request.
4. Data: checksum bench_tpl == db/checksums.txt.

Pakai: contract.py [--apps go,swift] [--record go]   (--record menulis ulang golden dari aplikasi itu; tinjau diff-nya)
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "lib"))
from benchenv import (APP_CONTAINERS, APP_PORTS, APP_SERVICES, ROOT, container_info, db_sh, dc, http, load_env,  # noqa: E402
                      log, mem_bytes, psql, sh, wait_http)

CT = os.path.join(ROOT, "contract-tests")
GOLD = os.path.join(CT, "golden")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
FIXTURE_MAX_TS = "2026-01-01"  # timestamp fixture semuanya < 2026; yang lebih baru = dinamis (hasil tulis)

failures = []


def fail(msg):
    failures.append(msg)
    log("  GAGAL: " + msg)


def normalize(v):
    if isinstance(v, dict):
        return {k: normalize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [normalize(x) for x in v]
    if isinstance(v, str) and TS_RE.match(v) and v >= FIXTURE_MAX_TS:
        return "<ts>"
    return v


def load_cases():
    return json.load(open(os.path.join(CT, "cases.json")))["cases"]


def start_app(app, mode, env):
    other = "swift" if app == "go" else "go"
    dc(["--dev", "stop", APP_SERVICES[other]], env=env, check=False)
    db_sh(["fixture-reset"], env=env)
    e = dict(env, LOG_MODE=mode, DB_NAME="fixture")
    dc(["--dev", "up", "-d", "--force-recreate", APP_SERVICES[app]], env=e)
    wait_http(APP_PORTS[app], timeout=60)


def reset_stats():
    psql("fixture", "SELECT pg_stat_statements_reset();")


def query_stats():
    rows = psql("fixture", """
SELECT s.calls, regexp_replace(s.query, '\\s+', ' ', 'g')
FROM pg_stat_statements s JOIN pg_database d ON d.oid = s.dbid
WHERE d.datname = 'fixture' AND s.query NOT ILIKE '%pg_stat_statements%' ORDER BY s.query;""")
    out = []
    for line in rows.splitlines():
        if "\t" in line:
            c, q = line.split("\t", 1)
            out.append((int(c), q))
    return out


def run_cases(app, mode, record, summary):
    port = APP_PORTS[app]
    res = {}
    for c in load_cases():
        reset_stats()
        st, body, hdr = http(port, c["method"], c["path"], body=c.get("body"), raw=c.get("raw_body"))
        time.sleep(0.05)
        stats = query_stats()
        calls = sum(n for n, _ in stats)
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"__non_json__": body.decode(errors="replace")[:200]}
        norm = {"status": st, "body": normalize(parsed)}
        ctype = hdr.get("content-type") or hdr.get("Content-Type") or ""
        if "application/json" not in ctype:
            fail("%s/%s %s: content-type %r bukan application/json" % (app, mode, c["name"], ctype))
        gpath = os.path.join(GOLD, c["name"] + ".json")
        if record:
            os.makedirs(GOLD, exist_ok=True)
            json.dump(norm, open(gpath, "w"), indent=1, sort_keys=True)
            open(gpath, "a").write("\n")
        else:
            if not os.path.exists(gpath):
                fail("%s/%s %s: golden tidak ada" % (app, mode, c["name"]))
            else:
                gold = json.load(open(gpath))
                if gold != norm:
                    fail("%s/%s %s: respons != golden\n    got : %s\n    gold: %s" % (
                        app, mode, c["name"], json.dumps(norm, sort_keys=True)[:400], json.dumps(gold, sort_keys=True)[:400]))
        if st != c["status"]:
            fail("%s/%s %s: status %d != %d" % (app, mode, c["name"], st, c["status"]))
        if calls != c["queries"]:
            fail("%s/%s %s: query/request %d != %d (%s)" % (app, mode, c["name"], calls, c["queries"],
                                                          "; ".join("%dx %s" % (n, q[:90]) for n, q in stats)))
        res[c["name"]] = {"status": st, "queries": calls, "sql": [{"calls": n, "query": q} for n, q in stats]}
    summary.setdefault("cases", {})[app + "/" + mode] = res
    log("  kontrak %s/%s: %d kasus diperiksa" % (app, mode, len(res)))
    return res


def check_side_effects():
    """Efek tulis harus benar-benar tersimpan (diperiksa langsung ke DB, di luar kode aplikasi)."""
    pay = psql("fixture", "SELECT count(*) FROM payments WHERE order_id = 7 AND amount_cents = (SELECT total_cents FROM orders WHERE id = 7);")
    st = psql("fixture", "SELECT status FROM orders WHERE id = 7;")
    if pay != "1" or st != "paid":
        fail("efek pay tidak tersimpan: payments=%s status=%s" % (pay, st))
    n = psql("fixture", "SELECT count(*) FROM orders WHERE id > 100;")
    if n != "3":
        fail("jumlah order baru %s != 3" % n)
    p404 = psql("fixture", "SELECT count(*) FROM payments WHERE order_id = 999;")
    if p404 != "0":
        fail("pay 404 meninggalkan payment")


def host_pid_status(pid, env):
    r = sh(["docker", "run", "--rm", "--pid=host", env["ALPINE_IMAGE"], "sh", "-c",
            "grep -E '^(Threads|VmRSS)' /proc/%d/status" % pid], env=env)
    return r.stdout.strip().replace("\n", " ")


def check_config(app, mode, env, summary):
    name = APP_CONTAINERS[app]
    info = container_info(name)
    hc = info["HostConfig"]
    cpus = int(env["APP_CPUS"])
    if hc["NanoCpus"] != cpus * 10 ** 9:
        fail("%s: NanoCpus %s != %d CPU" % (app, hc["NanoCpus"], cpus))
    if hc["Memory"] != mem_bytes(env["APP_MEM"]):
        fail("%s: Memory %s != %s" % (app, hc["Memory"], env["APP_MEM"]))
    if hc["CpusetCpus"] != env["APP_CPUSET"]:
        fail("%s: cpuset %r != %r" % (app, hc["CpusetCpus"], env["APP_CPUSET"]))
    if info["Config"]["User"] in ("", "0", "root"):
        fail("%s: container berjalan sebagai root" % app)
    total = int(env["DB_POOL_TOTAL"])
    cfg = {"image_user": info["Config"]["User"], "cpus": cpus, "pool_total_planned": total}

    # beban singkat agar pool terisi, lalu hitung koneksi di sisi Postgres
    port = APP_PORTS[app]

    def hit(i):
        return http(port, "GET", "/users/%d" % (1 + i % 20))[0]

    with concurrent.futures.ThreadPoolExecutor(max_workers=48) as ex:
        codes = list(ex.map(hit, range(600)))
    if any(c != 200 for c in codes):
        fail("%s: burst GET /users/{id} menghasilkan non-200" % app)
    conns = int(psql("fixture", "SELECT count(*) FROM pg_stat_activity WHERE datname='fixture' AND backend_type='client backend' AND pid <> pg_backend_pid();"))
    cfg["pg_connections_after_burst"] = conns
    if conns > total:
        fail("%s: koneksi Postgres %d > total pool %d" % (app, conns, total))
    if conns < 2:
        fail("%s: koneksi Postgres %d terlalu sedikit (pool tidak terpakai?)" % (app, conns))

    if app == "go":
        st, body, _ = http(6060, "GET", "/metrics/runtime")
        m = json.loads(body)
        cfg["gomaxprocs"] = m["gomaxprocs"]
        cfg["db_max_open"] = m.get("db_max_open")
        if m["gomaxprocs"] != cpus:
            fail("go: GOMAXPROCS %s != %d" % (m["gomaxprocs"], cpus))
        if m.get("db_max_open") != total:
            fail("go: SetMaxOpenConns %s != %d" % (m.get("db_max_open"), total))
    else:
        out = sh(["docker", "logs", name], env=env).stdout
        mm = re.search(r"event_loops: (\d+).*pool_per_loop: (\d+)|pool_per_loop: (\d+).*event_loops: (\d+)", out)
        if not mm:
            fail("swift: log startup tidak memuat event_loops/pool_per_loop")
        else:
            g = [x for x in mm.groups() if x]
            ev, ppl = (int(g[0]), int(g[1])) if mm.group(1) else (int(g[1]), int(g[0]))
            cfg["event_loops"], cfg["pool_per_loop"] = ev, ppl
            if ev != cpus:
                fail("swift: event loop %d != %d CPU" % (ev, cpus))
            if ev * ppl != total:
                fail("swift: %d x %d != total pool %d" % (ppl, ev, total))
    cfg["proc_status"] = host_pid_status(info["State"]["Pid"], env)
    summary.setdefault("config", {})[app + "/" + mode] = cfg
    log("  konfigurasi %s/%s: %s" % (app, mode, json.dumps(cfg)))


def check_protocol(app, env, summary):
    """Bukti extended protocol (bukan simple query) dan jenis statement (bernama/di-cache vs tanpa nama), dari log Postgres."""
    e = dict(env, LOG_MODE="quiet", DB_NAME="fixture")
    db_sh(["fixture-reset"], env=env)
    psql("postgres", "ALTER DATABASE fixture SET log_statement='all'; ALTER DATABASE fixture SET log_min_messages='log';")
    try:
        dc(["--dev", "up", "-d", "--force-recreate", APP_SERVICES[app]], env=e)
        wait_http(APP_PORTS[app])
        time.sleep(1.0)
        mark = time.time()
        for i in range(6):
            http(APP_PORTS[app], "GET", "/users/%d" % (1 + i))
        time.sleep(1.0)
        out = subprocess.run(["docker", "logs", "bench-postgres", "--since", "%ds" % int(time.time() - mark + 1)],
                             capture_output=True, text=True)
        lines = [l for l in (out.stdout + out.stderr).splitlines() if "LOG:" in l and "FROM \"users\"" in l]
    finally:
        psql("postgres", "ALTER DATABASE fixture RESET log_statement; ALTER DATABASE fixture RESET log_min_messages;")
    execs = [l for l in lines if re.search(r"LOG:\s+execute ", l)]
    simple = [l for l in lines if re.search(r"LOG:\s+statement: ", l)]
    named = [l for l in execs if "<unnamed>" not in l]
    kind = "simple-protocol" if simple and not execs else ("extended/named-prepared" if named else ("extended/unnamed" if execs else "unknown"))
    summary.setdefault("protocol", {})[app] = {"kind": kind, "execs_seen": len(execs)}
    log("  protokol %s: %s (%d eksekusi terlihat)" % (app, kind, len(execs)))
    if kind in ("simple-protocol", "unknown"):
        fail("%s: tidak memakai extended protocol (%s)" % (app, kind))


def split_logs(name):
    r = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
    return r.stdout.splitlines(), r.stderr.splitlines()


def check_logging(app, mode, summary):
    name = APP_CONTAINERS[app]
    port = APP_PORTS[app]
    reqs = [("GET", "/healthz"), ("GET", "/bench/json"), ("GET", "/users/1"), ("GET", "/users/999"), ("GET", "/users/abc"),
            ("GET", "/users/2/orders?limit=3"), ("GET", "/nope")] * 4 + [("GET", "/healthz")] * 2
    time.sleep(1.0)
    before_out, before_err = split_logs(name)
    for m, p in reqs:
        http(port, m, p)
    time.sleep(1.0)
    after_out, after_err = split_logs(name)
    d_out, d_err = len(after_out) - len(before_out), len(after_err) - len(before_err)
    n = len(reqs)
    per = {"requests": n, "new_lines_stdout": d_out, "new_lines_stderr": d_err, "startup_lines": len(before_out)}
    if mode == "quiet" and (d_out + d_err) != 0:
        fail("%s quiet: %d baris log baru (harus 0): %s" % (app, d_out + d_err, " | ".join(after_out[len(before_out):][:3])))
    if mode == "access" and (d_out + d_err) != n:
        fail("%s access: %d baris untuk %d request (harus tepat 1 per request)" % (app, d_out + d_err, n))
    if d_err != 0 or after_err:
        fail("%s %s: log tertulis ke stderr (%d baris); harus stdout" % (app, mode, len(after_err)))
    if not before_out:
        fail("%s %s: log startup tidak tertulis" % (app, mode))
    if mode == "access":
        per["sample_line"] = after_out[-1] if after_out else ""
        per["bytes_per_request"] = round(sum(len(x) + 1 for x in after_out[len(before_out):]) / n, 1)
    summary.setdefault("logging", {})[app + "/" + mode] = per
    log("  logging %s/%s: %s" % (app, mode, json.dumps(per)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apps", default="go,swift")
    ap.add_argument("--record", default="", help="tulis ulang golden dari aplikasi ini (go|swift)")
    a = ap.parse_args()
    env = load_env()
    apps = a.apps.split(",")
    summary = {"profile": env["PROFILE"], "image_flavor": env["IMAGE_FLAVOR"], "variant": env["VARIANT"],
               "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    log("== Gerbang 0: tata letak lapisan (paket Go / target Swift)")
    r = subprocess.run([sys.executable, os.path.join(CT, "check_layout.py")], capture_output=True, text=True)
    log(r.stdout.rstrip())
    if r.returncode != 0:
        fail("tata letak lapisan tidak sesuai")

    log("== Gerbang 4: checksum seed")
    r = db_sh(["verify"], env=env, check=False)
    log(r.stdout.rstrip())
    if r.returncode != 0:
        fail("checksum seed tidak cocok")
    summary["seed_checksums"] = open(os.path.join(ROOT, "db", "checksums.txt")).read().strip().splitlines()

    db_sh(["fixture"], env=env)
    for app in apps:
        log("== build image %s (%s)" % (app, env["IMAGE_FLAVOR"]))
        dc(["build", APP_SERVICES[app]], env=env)
        for mode in ("quiet", "access"):
            log("== %s mode=%s" % (app, mode))
            start_app(app, mode, env)
            record = a.record == app and mode == "quiet"
            run_cases(app, mode, record, summary)
            if mode == "quiet":
                check_side_effects()
            check_config(app, mode, env, summary)
            check_logging(app, mode, summary)
        check_protocol(app, env, summary)
    # perbandingan silang jumlah query antar aplikasi
    if len(apps) == 2:
        for c in load_cases():
            q = [summary["cases"][x + "/quiet"][c["name"]]["queries"] for x in apps]
            if q[0] != q[1]:
                fail("query/request berbeda antar aplikasi di %s: %s" % (c["name"], q))
    for app in apps:
        dc(["--dev", "stop", APP_SERVICES[app]], env=env, check=False)

    out_dir = os.path.join(ROOT, "results", "raw", "contract")
    os.makedirs(out_dir, exist_ok=True)
    summary["failures"] = failures
    json.dump(summary, open(os.path.join(out_dir, "summary.json"), "w"), indent=1)
    if failures:
        log("\nCONTRACT GAGAL (%d masalah)" % len(failures))
        return 1
    log("\nCONTRACT LULUS: kontrak, jumlah query, konfigurasi, logging, dan checksum sama di %s" % ", ".join(apps))
    return 0


if __name__ == "__main__":
    sys.exit(main())
