# Satu pintu masuk. Kompatibel GNU Make 3.81 (bawaan macOS): tanpa .ONESHELL, grouped targets, atau fungsi Make 4.
# Logika panjang ada di tools/. 'make help' mencetak semua target. Variabel dibaca dari .env bila ada.
SHELL := /bin/bash
.DEFAULT_GOAL := help

-include .env

APP           ?= both
SCENARIO      ?= core
REPEATS       ?= 3
PROFILE       ?= mac-m2
SLO_P99_MS    ?= 250
LOG_MODE      ?= quiet
LOG_FORMAT    ?= text
VARIANT       ?= default
BUILD_CONFIG  ?= both
DURATION      ?= 45
IMAGE_FLAVOR  ?= distroless
SCALE_CPUS    ?= 1,2,3
MODULES       ?= 1,5,20
export APP SCENARIO REPEATS PROFILE SLO_P99_MS LOG_MODE LOG_FORMAT VARIANT BUILD_CONFIG DURATION IMAGE_FLAVOR SCALE_CPUS MODULES
ifneq ($(BUILD_REPEATS),)
export BUILD_REPEATS
endif

# Benchmark beban dibungkus caffeinate -dims bila tersedia
CAFF := $(shell command -v caffeinate >/dev/null 2>&1 && echo "caffeinate -dims")
DC   := tools/dc.sh
DB   := tools/db.sh
PY   := python3
# Konfigurasi native untuk go-run/swift-run (Postgres dari 'make db-up', port 54322)
NATIVE_ENV := DB_HOST=localhost DB_PORT=54322 DB_USER=bench DB_PASSWORD=bench DB_NAME=bench PORT=$(if $(NATIVE_PORT),$(NATIVE_PORT),8080) ADMIN_PORT=6060 LOG_MODE=$(LOG_MODE) LOG_FORMAT=$(LOG_FORMAT)

.PHONY: help doctor doctor-docker doctor-native \
	db-up db-down db-seed db-reset db-psql \
	go-build go-run go-test go-image go-up go-down go-logs \
	swift-build swift-run swift-test swift-image swift-up swift-down swift-logs \
	contract bench-smoke bench-core bench bench-tuned startup-bench \
	build-bench build-bench-clean build-bench-incr build-bench-cached \
	profile dx-bench scale-bench modular-bench report clean clean-all

help: ## Daftar target dan variabel
	@echo "Variabel: APP=go|swift|both SCENARIO=s1,s3,..|core|all REPEATS PROFILE SLO_P99_MS LOG_MODE=quiet|access"
	@echo "          LOG_FORMAT=text|json VARIANT=default|tuned IMAGE_FLAVOR=distroless|alpine BUILD_REPEATS BUILD_CONFIG=dev|release|both"
	@echo "          DURATION SCALE_CPUS MODULES   (juga dibaca dari .env)"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z0-9_-]+):[^#]*## (.*)$$/\1\t\2/' | awk -F'\t' '{printf "  %-22s %s\n", $$1, $$2}'

doctor: ## Cek prasyarat (arm64, Docker, VM, image, sampler/cgroup, toolchain native, charger, thermal)
	@tools/doctor.sh docker; d=$$?; tools/doctor.sh native; n=$$?; \
	if [ $$n -ne 0 ]; then echo; echo ">> build-bench, profile, dx-bench, modular-bench DITOLAK sampai toolchain native terpenuhi."; fi; \
	exit $$d

doctor-docker: ## (internal) gerbang prasyarat Docker
	@tools/doctor.sh docker >/dev/null || { tools/doctor.sh docker; exit 1; }

doctor-native: ## (internal) gerbang prasyarat toolchain native
	@tools/doctor.sh native >/dev/null || { tools/doctor.sh native; echo; echo "DITOLAK: butuh Go 1.27.2 dan Swift 6.4 native (tidak dipasang otomatis)."; exit 1; }

# ---- Database
db-up: ## Jalankan Postgres (port 54322, named volume)
	@$(DB) up

db-down: ## Hentikan Postgres (data tetap di volume)
	@$(DB) down

db-seed: db-up ## Seed 10k user + 500k order, VACUUM ANALYZE, checksum, ekspor ID, buat template bench_tpl
	@$(DB) seed

db-reset: ## Reset DB bench dari template bench_tpl
	@$(DB) reset

db-psql: ## Buka psql ke DB bench
	@$(DB) psql

# ---- Go
go-build: ## Build native Go (dev) ke bin/go-server
	@mkdir -p bin && cd go-app && go build -o ../bin/go-server ./cmd/server && echo "bin/go-server"

go-run: ## Jalankan Go native di :8080 (butuh make db-up db-seed)
	@cd go-app && $(NATIVE_ENV) go run ./cmd/server

go-test: ## go test ./... (suite paritas)
	@cd go-app && go test ./...

go-image: ## Bangun image Go (IMAGE_FLAVOR)
	@$(DC) build go-app

go-up: ## Jalankan Go di container dengan batas profil (publish 8080/6060 untuk dev)
	@$(DC) --dev stop swift-app >/dev/null 2>&1 || true
	@$(DC) --dev up -d --build go-app

go-down: ## Hentikan container Go
	@$(DC) --dev stop go-app

go-logs: ## Ikuti log container Go
	@$(DC) --dev logs -f go-app

# ---- Swift (native bila toolchain 6.4 ada, jika tidak jatuh ke container)
swift-build: ## Build Swift native (debug); tanpa toolchain 6.4 -> membangun image di container
	@if swift --version 2>/dev/null | grep -q "Swift version 6.4"; then cd swift-app && swift build; \
	else echo "Toolchain Swift 6.4 native tidak ada: membangun di container (swift-image)"; $(MAKE) swift-image; fi

swift-run: ## Jalankan Swift native di :8081 (tanpa toolchain -> swift-up di container)
	@if swift --version 2>/dev/null | grep -q "Swift version 6.4"; then cd swift-app && $(NATIVE_ENV) PORT=8081 EVENT_LOOPS=2 DB_POOL=16 swift run App; \
	else echo "Toolchain Swift 6.4 native tidak ada: menjalankan di container (swift-up)"; $(MAKE) swift-up; fi

swift-test: ## swift test (Swift Testing, suite paritas)
	@cd swift-app && swift test

swift-image: ## Bangun image Swift (IMAGE_FLAVOR)
	@$(DC) build swift-app

swift-up: ## Jalankan Swift di container dengan batas profil (publish 8081 untuk dev)
	@$(DC) --dev stop go-app >/dev/null 2>&1 || true
	@$(DC) --dev up -d --build swift-app

swift-down: ## Hentikan container Swift
	@$(DC) --dev stop swift-app

swift-logs: ## Ikuti log container Swift
	@$(DC) --dev logs -f swift-app

# ---- Gerbang kesetaraan dan benchmark beban (selalu di container)
contract: doctor-docker ## Gerbang kesetaraan: kontrak/golden, jumlah query, konfigurasi, logging, checksum
	@$(PY) contract-tests/contract.py --apps $(if $(filter both,$(APP)),go$(comma)swift,$(APP))

comma := ,

bench-smoke: doctor-docker ## Smoke (<15 menit): semua skenario P0, 1 ulangan, durasi pendek. Angka berlabel 'smoke, bukan final'
	@$(CAFF) $(PY) tools/bench.py smoke

bench-core: doctor-docker ## Skenario inti S1,S3,S4,S8 (tahap A+B, REPEATS ulangan)
	@$(CAFF) $(PY) tools/bench.py run --scenarios s1,s3,s4,s8

bench: doctor-docker ## Benchmark penuh (APP, SCENARIO, REPEATS); mencetak estimasi durasi. Berjam-jam
	@$(CAFF) $(PY) tools/bench.py run --scenarios $(SCENARIO)

bench-tuned: doctor-docker ## S13: varian tuned (S3,S4,S8) + sapuan pool 8,16,32,64 (docker-compose.tuned.yml)
	@$(CAFF) $(PY) tools/bench.py tuned

startup-bench: doctor-docker ## S12: ukuran image, waktu start, request pertama, memori idle (10 ulangan, kedua flavor)
	@$(CAFF) $(PY) tools/startup_bench.py

scale-bench: doctor-docker ## S14/SC1: skala vertikal SCALE_CPUS (S3, S8 tahap A), efisiensi RPS(n)/(n*RPS(1))
	@$(CAFF) $(PY) tools/bench.py scale

# ---- Native macOS (tidak boleh bersamaan dengan beban Docker)
build-bench: doctor-native ## Build time B1+B2+B3 (BUILD_REPEATS, BUILD_CONFIG=dev|release|both), native, cache terisolasi
	@$(CAFF) $(PY) tools/buildtime/buildtime.py all

build-bench-clean: doctor-native ## B1: build bersih tanpa cache
	@$(CAFF) $(PY) tools/buildtime/buildtime.py b1

build-bench-incr: doctor-native ## B2: build ulang setelah ubah satu file
	@$(CAFF) $(PY) tools/buildtime/buildtime.py b2

build-bench-cached: doctor-native ## B3: dependency ter-cache, artefak dibuang
	@$(CAFF) $(PY) tools/buildtime/buildtime.py b3

profile: doctor-native doctor-docker ## Profil native (APP=go|swift SCENARIO=s8 DURATION=45) pada 50% saturasi
	@$(PY) tools/profile.py

dx-bench: doctor-native ## DX1..DX5: edit->siap, waktu test, ukuran kode, diagnostik compiler, onboarding
	@$(CAFF) $(PY) tools/dx/dx_bench.py

modular-bench: doctor-native ## M1/SC3: proyek sintetis N modul (MODULES), topologi T1/T2, B3/B2-leaf/B2-core
	@$(CAFF) $(PY) tools/modgen/modular_bench.py

report: ## Bangun results/report.md, CSV agregat, dan grafik PNG
	@$(PY) tools/report/report.py

clean: ## Hapus hasil run, artefak build lokal, dan container benchmark
	@$(DC) --dev down --remove-orphans >/dev/null 2>&1 || true
	rm -rf results/raw results/profiles results/*.csv results/*.png results/report.md bin swift-app/.build go-app/server

clean-all: clean ## clean + hapus image bench-* dan volume Postgres (data seed hilang)
	@$(DC) --dev down -v --remove-orphans >/dev/null 2>&1 || true
	-docker image rm bench-go:distroless bench-go:alpine bench-swift:distroless bench-swift:alpine bench-sampler:latest 2>/dev/null
