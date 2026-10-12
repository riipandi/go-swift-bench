#!/usr/bin/env python3
"""Memeriksa daftar paket Go dan target Swift terhadap arsitektur setara, dependency satu arah, tanpa siklus."""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# lapisan -> dependency internal yang diizinkan (HTTP -> Store -> Domain; Platform dipakai dari atas)
RULES = {
    "domain": set(),
    "store": {"domain"},
    "httpapi": {"domain", "store"},
    "platform": set(),
    "app": {"domain", "store", "httpapi", "platform"},  # cmd/server atau executable App
}


def find_cycle(graph):
    state = {}

    def dfs(n, path):
        state[n] = 1
        for m in graph.get(n, ()):
            if state.get(m) == 1:
                return path + [n, m]
            if m not in state:
                c = dfs(m, path + [n])
                if c:
                    return c
        state[n] = 2
        return None

    for n in graph:
        if n not in state:
            c = dfs(n, [])
            if c:
                return c
    return None


def check_go():
    errs = []
    out = subprocess.run(["go", "list", "-f", "{{.ImportPath}}|{{join .Imports \",\"}}", "./..."],
                         cwd=os.path.join(ROOT, "go-app"), capture_output=True, text=True)
    if out.returncode != 0:
        return ["go list gagal: " + out.stderr.strip()]
    graph = {}
    for line in out.stdout.strip().splitlines():
        pkg, imps = line.split("|", 1)
        graph[pkg.replace("benchapp/", "")] = {i.replace("benchapp/", "") for i in imps.split(",") if i.startswith("benchapp/")}
    expected = {"internal/domain": "domain", "internal/store": "store", "internal/httpapi": "httpapi",
                "internal/platform": "platform", "cmd/server": "app"}
    if set(graph) != set(expected):
        errs.append("daftar paket Go %s != %s" % (sorted(graph), sorted(expected)))
    for pkg, imps in graph.items():
        layer = expected.get(pkg)
        if not layer:
            continue
        got = {expected[i] for i in imps if i in expected}
        extra = got - RULES[layer]
        if extra:
            errs.append("Go %s mengimpor lapisan terlarang: %s" % (pkg, sorted(extra)))
    cyc = find_cycle(graph)
    if cyc:
        errs.append("siklus dependency Go: %s" % " -> ".join(cyc))
    return errs, graph


def swift_describe():
    swift = subprocess.run(["swift", "--version"], capture_output=True, text=True)
    if swift.returncode == 0 and "6.4" in swift.stdout:
        r = subprocess.run(["swift", "package", "describe", "--type", "json"], cwd=os.path.join(ROOT, "swift-app"),
                           capture_output=True, text=True)
    else:
        r = subprocess.run(["docker", "run", "--rm", "-v", os.path.join(ROOT, "swift-app") + ":/src:ro", "-w", "/src",
                            "swift:6.4-noble", "swift", "package", "describe", "--type", "json"],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("swift package describe gagal: " + r.stderr[-300:])
    out = r.stdout
    return json.loads(out[out.index("{"):])


def check_swift():
    errs = []
    d = swift_describe()
    graph = {}
    for t in d["targets"]:
        graph[t["name"]] = set(t.get("target_dependencies", []))
    expected = {"Domain": "domain", "Persistence": "store", "HTTPAPI": "httpapi", "Platform": "platform", "App": "app"}
    prod = {n for n in graph if n not in ("ParityTests",)}
    if prod != set(expected):
        errs.append("daftar target Swift %s != %s" % (sorted(prod), sorted(expected)))
    for n, deps in graph.items():
        layer = expected.get(n)
        if not layer:
            continue
        got = {expected[i] for i in deps if i in expected}
        extra = got - RULES[layer]
        if extra:
            errs.append("Swift target %s bergantung pada lapisan terlarang: %s" % (n, sorted(extra)))
    cyc = find_cycle(graph)
    if cyc:
        errs.append("siklus dependency Swift: %s" % " -> ".join(cyc))
    return errs, graph


def main():
    ok = True
    res = check_go()
    errs, g = res if isinstance(res, tuple) else (res, {})
    print("Go    paket :", {k: sorted(v) for k, v in sorted(g.items())})
    for e in errs:
        print("  GAGAL:", e)
    ok &= not errs
    errs, g = check_swift()
    print("Swift target:", {k: sorted(v) for k, v in sorted(g.items())})
    for e in errs:
        print("  GAGAL:", e)
    ok &= not errs
    print("LAYOUT:", "OK" if ok else "GAGAL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
