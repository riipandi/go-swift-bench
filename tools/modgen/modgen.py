"""Generator proyek sintetis untuk eksperimen M1 (SC3): N modul, dua topologi per stack.

Tiap modul daun ~100 baris (model, validasi, handler) dan hanya bergantung pada modul inti 'core' serta dependency yang sama
dengan aplikasi (Go: chi + encoding/json; Swift: Vapor + Codable).

  Go    T1: satu module 'synth' dengan N package (core, mod001..)       T2: N+2 module dalam go.work
  Swift T1: satu paket dengan N+1 target (Core, Mod001..)              T2: N+2 paket lokal lewat path
"""
import os
import re
import shutil

CHI_VERSION_FILE = "go-app/go.mod"


def pad(i):
    return "%03d" % i


# ------------------------------------------------------------------ Go
GO_CORE = '''package core

import (
	"encoding/json"
	"net/http"
)

// Version adalah literal yang diubah pada B2-core.
const Version = "core-v0"

// Validator dipakai semua modul daun.
type Validator interface{ Validate() error }

type ErrorBody struct {
	Error string `json:"error"`
}

func WriteJSON(w http.ResponseWriter, status int, v any) {
	b, err := json.Marshal(v)
	if err != nil {
		w.WriteHeader(http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(b)
}

func Clamp(x, lo, hi int) int {
	if x < lo {
		return lo
	}
	if x > hi {
		return hi
	}
	return x
}

func Decode[T Validator](r *http.Request, v *T) error {
	if err := json.NewDecoder(r.Body).Decode(v); err != nil {
		return err
	}
	return (*v).Validate()
}
'''


def go_mod_file(i):
    n = pad(i)
    body = '''package mod%(n)s

import (
	"errors"
	"net/http"
	"strings"

	"example.test/synth/core"

	"github.com/go-chi/chi/v5"
)

// Name adalah literal yang diubah pada B2-leaf.
const Name = "mod%(n)s-v0"

type Item struct {
	ID     int64    `json:"id"`
	Name   string   `json:"name"`
	Email  string   `json:"email"`
	Score  int      `json:"score"`
	Tags   []string `json:"tags"`
	Active bool     `json:"active"`
}

func (it Item) Validate() error {
	if it.ID <= 0 {
		return errors.New("id must be positive")
	}
	if strings.TrimSpace(it.Name) == "" {
		return errors.New("name is required")
	}
	if !strings.Contains(it.Email, "@") {
		return errors.New("email is invalid")
	}
	if it.Score < 0 || it.Score > 1000 {
		return errors.New("score out of range")
	}
	if len(it.Tags) > 16 {
		return errors.New("too many tags")
	}
	return nil
}

func (it Item) Normalized() Item {
	it.Name = strings.TrimSpace(it.Name)
	it.Email = strings.ToLower(it.Email)
	it.Score = core.Clamp(it.Score, 0, 1000)
	for i := range it.Tags {
		it.Tags[i] = strings.ToLower(strings.TrimSpace(it.Tags[i]))
	}
	return it
}

func create(w http.ResponseWriter, r *http.Request) {
	var it Item
	if err := core.Decode(r, &it); err != nil {
		core.WriteJSON(w, http.StatusBadRequest, core.ErrorBody{Error: err.Error()})
		return
	}
	core.WriteJSON(w, http.StatusCreated, it.Normalized())
}

func health(w http.ResponseWriter, _ *http.Request) {
	core.WriteJSON(w, http.StatusOK, map[string]string{"module": Name, "core": core.Version})
}

// Routes memasang route modul ini.
func Routes(r chi.Router) {
	r.Get("/mod%(n)s/health", health)
	r.Post("/mod%(n)s/items", create)
}
''' % {"n": n}
    # isi tambahan (filler deterministik) agar ~100 baris
    extra = "".join('''
func helper%(k)d(x int) int {
	y := x*%(m)d + %(k)d
	if y%%2 == 0 {
		return y / 2
	}
	return core.Clamp(y, 0, %(c)d)
}
''' % {"k": k, "m": i + k + 3, "c": 100 * (k + 1)} for k in range(6))
    return body + extra


GO_MAIN_HEAD = '''package main

import (
	"fmt"
	"net/http"

	"example.test/synth/core"
%(imports)s
	"github.com/go-chi/chi/v5"
)

func main() {
	r := chi.NewRouter()
%(routes)s
	fmt.Println(core.Version, len(r.Routes()))
	_ = http.StatusOK
}
'''


def gen_go(topo, n, dest, root):
    """Kembalikan dict info proyek. topo: T1 | T2."""
    chi_req = [l.strip() for l in open(os.path.join(root, CHI_VERSION_FILE)) if "go-chi/chi" in l][0].split("//")[0].strip()
    go_sum = open(os.path.join(root, "go-app", "go.sum")).read()
    go_ver = "1.27.2"
    mods = [pad(i) for i in range(1, n + 1)]
    imports = "".join('\t"example.test/synth/mod%s"\n' % m for m in mods)
    routes = "".join("\tmod%s.Routes(r)\n" % m for m in mods)
    main_src = GO_MAIN_HEAD % {"imports": imports, "routes": routes}
    info = {"stack": "go", "topology": topo, "n": n}
    if topo == "T1":
        os.makedirs(os.path.join(dest, "cmd", "app"), exist_ok=True)
        os.makedirs(os.path.join(dest, "core"))
        open(os.path.join(dest, "go.mod"), "w").write("module example.test/synth\n\ngo %s\n\nrequire %s\n" % (go_ver, chi_req))
        open(os.path.join(dest, "go.sum"), "w").write(go_sum)
        open(os.path.join(dest, "core", "core.go"), "w").write(GO_CORE)
        for i in range(1, n + 1):
            os.makedirs(os.path.join(dest, "mod" + pad(i)))
            open(os.path.join(dest, "mod" + pad(i), "mod.go"), "w").write(go_mod_file(i))
        open(os.path.join(dest, "cmd", "app", "main.go"), "w").write(main_src)
        info.update(cwd=dest, build=["go", "build", "-o", "{out}", "./cmd/app"], core_file=os.path.join(dest, "core", "core.go"),
                    leaf_file=os.path.join(dest, "mod" + pad(n), "mod.go"))
    else:
        def write_mod(path, modpath, requires):
            os.makedirs(path, exist_ok=True)
            req = "".join("\t%s v0.0.0\n" % r for r in requires)
            # replace ke direktori lokal (modul belum diterbitkan); tetap dikelola lewat go.work
            rep = "".join("replace %s => ../%s\n" % (r, r.rsplit("/", 1)[1]) for r in requires)
            open(os.path.join(path, "go.mod"), "w").write("module %s\n\ngo %s\n\nrequire (\n%s\t%s\n)\n\n%s" % (modpath, go_ver, req, chi_req, rep))
            open(os.path.join(path, "go.sum"), "w").write(go_sum)
        write_mod(os.path.join(dest, "core"), "example.test/synth/core", [])
        open(os.path.join(dest, "core", "core.go"), "w").write(GO_CORE)
        for i in range(1, n + 1):
            write_mod(os.path.join(dest, "mod" + pad(i)), "example.test/synth/mod" + pad(i), ["example.test/synth/core"])
            open(os.path.join(dest, "mod" + pad(i), "mod.go"), "w").write(go_mod_file(i))
        write_mod(os.path.join(dest, "app"), "example.test/synth/app", ["example.test/synth/core"] + ["example.test/synth/mod" + m for m in mods])
        open(os.path.join(dest, "app", "main.go"), "w").write(main_src)
        uses = "".join("\t./mod%s\n" % m for m in mods)
        open(os.path.join(dest, "go.work"), "w").write("go %s\n\nuse (\n\t./core\n\t./app\n%s)\n" % (go_ver, uses))
        info.update(cwd=os.path.join(dest, "app"), build=["go", "build", "-o", "{out}", "."], core_file=os.path.join(dest, "core", "core.go"),
                    leaf_file=os.path.join(dest, "mod" + pad(n), "mod.go"))
    info.update(core_literal='"core-v0"', leaf_literal='"mod%s-v0"' % pad(n))
    return info


# ------------------------------------------------------------------ Swift
SW_CORE = '''import Vapor

public enum Core {
    /// Literal yang diubah pada B2-core.
    public static let version = "core-v0"

    public static func clamp(_ x: Int, _ lo: Int, _ hi: Int) -> Int {
        if x < lo { return lo }
        if x > hi { return hi }
        return x
    }

    public static func fail(_ reason: String) -> Abort {
        Abort(.badRequest, reason: reason)
    }
}

public protocol Validatable2: Content {
    func check() throws
}
'''


def sw_mod_file(i):
    n = pad(i)
    body = '''import Core
import Vapor

public enum Mod%(n)s {
    /// Literal yang diubah pada B2-leaf.
    public static let name = "mod%(n)s-v0"
}

public struct Item%(n)s: Validatable2, Sendable {
    public var id: Int
    public var name: String
    public var email: String
    public var score: Int
    public var tags: [String]
    public var active: Bool

    public func check() throws {
        if id <= 0 { throw Core.fail("id must be positive") }
        if name.trimmingCharacters(in: .whitespaces).isEmpty { throw Core.fail("name is required") }
        if !email.contains("@") { throw Core.fail("email is invalid") }
        if score < 0 || score > 1000 { throw Core.fail("score out of range") }
        if tags.count > 16 { throw Core.fail("too many tags") }
    }

    public func normalized() -> Item%(n)s {
        var it = self
        it.name = name.trimmingCharacters(in: .whitespaces)
        it.email = email.lowercased()
        it.score = Core.clamp(score, 0, 1000)
        it.tags = tags.map { $0.trimmingCharacters(in: .whitespaces).lowercased() }
        return it
    }
}

public func register%(n)s(_ app: Application) {
    app.get("mod%(n)s", "health") { _ in "\\(Core.version)/\\(Mod%(n)s.name)" }
    app.post("mod%(n)s", "items") { req async throws -> Item%(n)s in
        let item = try req.content.decode(Item%(n)s.self)
        try item.check()
        return item.normalized()
    }
}
''' % {"n": n}
    extra = "".join('''
func helper%(n)s_%(k)d(_ x: Int) -> Int {
    let y = x * %(m)d + %(k)d
    if y %% 2 == 0 { return y / 2 }
    return Core.clamp(y, 0, %(c)d)
}
''' % {"n": n, "k": k, "m": i + k + 3, "c": 100 * (k + 1)} for k in range(6))
    return body + extra


def sw_pkg_deps(vapor_from):
    return '.package(url: "https://github.com/vapor/vapor.git", from: "%s")' % vapor_from


def gen_swift(topo, n, dest, root):
    vapor_from = re.search(r'vapor/vapor.git", from: "([^"]+)"', open(os.path.join(root, "swift-app", "Package.swift")).read()).group(1)
    resolved = os.path.join(root, "swift-app", "Package.resolved")
    mods = [pad(i) for i in range(1, n + 1)]
    app_src = "import Vapor\nimport Core\n" + "".join("import Mod%s\n" % m for m in mods) + '''
@main
enum Entry {
    static func main() async throws {
        let app = try await Application.make(.testing)
%s        print(Core.version, app.routes.all.count)
        try await app.asyncShutdown()
    }
}
''' % "".join("        register%s(app)\n" % m for m in mods)
    vapor_prod = '.product(name: "Vapor", package: "vapor")'
    info = {"stack": "swift", "topology": topo, "n": n}
    if topo == "T1":
        os.makedirs(os.path.join(dest, "Sources", "Core"))
        targets = ['.target(name: "Core", dependencies: [%s])' % vapor_prod]
        for m in mods:
            targets.append('.target(name: "Mod%s", dependencies: ["Core", %s])' % (m, vapor_prod))
            os.makedirs(os.path.join(dest, "Sources", "Mod" + m))
            open(os.path.join(dest, "Sources", "Mod" + m, "Mod.swift"), "w").write(sw_mod_file(int(m)))
        targets.append('.executableTarget(name: "App", dependencies: [%s])' % ", ".join(['"Core"'] + ['"Mod%s"' % m for m in mods] + [vapor_prod]))
        os.makedirs(os.path.join(dest, "Sources", "App"))
        open(os.path.join(dest, "Sources", "App", "Entry.swift"), "w").write(app_src)
        open(os.path.join(dest, "Sources", "Core", "Core.swift"), "w").write(SW_CORE)
        open(os.path.join(dest, "Package.swift"), "w").write(
            '// swift-tools-version:6.0\nimport PackageDescription\n\nlet package = Package(\n    name: "synth",\n    platforms: [.macOS(.v14)],\n'
            '    dependencies: [%s],\n    targets: [\n        %s,\n    ],\n    swiftLanguageModes: [.v5]\n)\n' % (sw_pkg_deps(vapor_from), ",\n        ".join(targets)))
        shutil.copy(resolved, os.path.join(dest, "Package.resolved"))
        info.update(cwd=dest, core_file=os.path.join(dest, "Sources", "Core", "Core.swift"),
                    leaf_file=os.path.join(dest, "Sources", "Mod" + pad(n), "Mod.swift"))
    else:
        def pkg(name, deps_local, product_deps, exe=False):
            path = os.path.join(dest, name)
            os.makedirs(os.path.join(path, "Sources", name))
            pk_deps = [sw_pkg_deps(vapor_from)] + ['.package(path: "../%s")' % d for d in deps_local]
            tdeps = ", ".join(product_deps + [vapor_prod])
            kind = ".executableTarget" if exe else ".target"
            prod = "" if exe else '    products: [.library(name: "%s", targets: ["%s"])],\n' % (name, name)
            open(os.path.join(path, "Package.swift"), "w").write(
                '// swift-tools-version:6.0\nimport PackageDescription\n\nlet package = Package(\n    name: "%s",\n    platforms: [.macOS(.v14)],\n%s'
                '    dependencies: [%s],\n    targets: [%s(name: "%s", dependencies: [%s])],\n    swiftLanguageModes: [.v5]\n)\n'
                % (name, prod, ", ".join(pk_deps), kind, name, tdeps))
            return path
        p = pkg("Core", [], [])
        open(os.path.join(p, "Sources", "Core", "Core.swift"), "w").write(SW_CORE)
        for m in mods:
            p = pkg("Mod" + m, ["Core"], ['.product(name: "Core", package: "Core")'])
            open(os.path.join(p, "Sources", "Mod" + m, "Mod.swift"), "w").write(sw_mod_file(int(m)))
        prod_deps = ['.product(name: "Core", package: "Core")'] + ['.product(name: "Mod%s", package: "Mod%s")' % (m, m) for m in mods]
        p = pkg("App", ["Core"] + ["Mod" + m for m in mods], prod_deps, exe=True)
        open(os.path.join(p, "Sources", "App", "Entry.swift"), "w").write(app_src)
        shutil.copy(resolved, os.path.join(p, "Package.resolved"))
        info.update(cwd=os.path.join(dest, "App"), core_file=os.path.join(dest, "Core", "Sources", "Core", "Core.swift"),
                    leaf_file=os.path.join(dest, "Mod" + pad(n), "Sources", "Mod" + pad(n), "Mod.swift"))
    info.update(build=["swift", "build", "--product", "App"], core_literal='"core-v0"', leaf_literal='"mod%s-v0"' % pad(n))
    return info


def generate(stack, topo, n, dest, root):
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    info = (gen_go if stack == "go" else gen_swift)(topo, n, dest, root)
    # ukuran kode per modul daun (baris non-kosong)
    leaf = open(info["leaf_file"]).read().splitlines()
    info["leaf_loc"] = sum(1 for l in leaf if l.strip() and not l.strip().startswith("//"))
    return info
