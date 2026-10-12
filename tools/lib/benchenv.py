"""Helper bersama untuk semua alat Python: env (sama dengan tools/lib/env.sh), perintah shell, docker, psql, HTTP."""
import http.client as httpc
import json
import os
import subprocess
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
APP_PORTS = {"go": 8080, "swift": 8081}          # port publish (hanya mode dev/contract/profil)
APP_SERVICES = {"go": "go-app", "swift": "swift-app"}
APP_CONTAINERS = {"go": "bench-go-app", "swift": "bench-swift-app"}


def _load_file(path, env):
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env.setdefault(k, v)


def load_env():
    """Prioritas: environment > .env > profil > images.conf (sama dengan env.sh)."""
    env = dict(os.environ)
    _load_file(os.path.join(ROOT, ".env"), env)
    profile = env.setdefault("PROFILE", "mac-m2")
    _load_file(os.path.join(ROOT, "profiles", profile + ".conf"), env)
    _load_file(os.path.join(ROOT, "profiles", "images.conf"), env)
    for k, v in {"IMAGE_FLAVOR": "distroless", "VARIANT": "default", "LOG_MODE": "quiet", "LOG_FORMAT": "text",
                 "SLO_P99_MS": "250", "REPEATS": "3"}.items():
        env.setdefault(k, v)
    cpus = int(env["APP_CPUS"])
    env.setdefault("DB_POOL_TOTAL", str(8 * cpus))
    env.setdefault("EVENT_LOOPS", str(cpus))
    env.setdefault("GOMAXPROCS_APP", str(cpus))
    env["ROOT"] = ROOT
    return env


def sh(cmd, env=None, check=True, capture=True, input=None, timeout=None):
    r = subprocess.run(cmd, shell=isinstance(cmd, str), env=env, check=False, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       stderr=subprocess.STDOUT if capture else None, input=input, timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError("perintah gagal (%d): %s\n%s" % (r.returncode, cmd, r.stdout or ""))
    return r


def dc(args, env=None, **kw):
    return sh([os.path.join(ROOT, "tools", "dc.sh")] + list(args), env=env, **kw)


def db_sh(args, env=None, **kw):
    return sh([os.path.join(ROOT, "tools", "db.sh")] + list(args), env=env, **kw)


def psql(db, sql, env=None):
    """Jalankan SQL di Postgres container (bukan kode aplikasi), kembalikan keluaran -At."""
    r = sh(["docker", "exec", "-i", "bench-postgres", "psql", "-v", "ON_ERROR_STOP=1", "-q", "-At", "-F", "\t",
            "-U", "bench", "-d", db], input=sql, env=env)
    return r.stdout.strip()


def container_info(name):
    r = sh(["docker", "inspect", name])
    return json.loads(r.stdout)[0]


def container_pid(name):
    return container_info(name)["State"]["Pid"]


def container_id(name):
    return container_info(name)["Id"]


def http(port, method, path, body=None, raw=None, timeout=15, host="127.0.0.1"):
    """Kembalikan (status, body_bytes, headers)."""
    c = httpc.HTTPConnection(host, port, timeout=timeout)
    headers = {}
    data = None
    if raw is not None:
        data = raw.encode()
        headers["Content-Type"] = "application/json"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    c.request(method, path, body=data, headers=headers)
    r = c.getresponse()
    b = r.read()
    h = dict(r.getheaders())
    c.close()
    return r.status, b, h


def wait_http(port, path="/healthz", timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            st, _, _ = http(port, "GET", path, timeout=2)
            if st == 200:
                return time.time() - t0
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("aplikasi tidak siap di port %d" % port)


def mem_bytes(s):
    s = s.strip().lower()
    mult = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
    if s[-1] in mult:
        return int(float(s[:-1]) * mult[s[-1]])
    return int(s)


def log(msg):
    print(msg, flush=True)
