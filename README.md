# Benchmark backend Go vs Swift

Dua backend API CRUD identik di atas satu Postgres, diukur dengan k6, semuanya lewat `make`:

| | Stack Go | Stack Swift |
|---|---|---|
| Bahasa | Go 1.27.2 | Swift 6.4.0 |
| HTTP / ORM | chi v5.3.2 / GORM v1.31.2 (`gorm.io/driver/postgres` v1.6.3) | Vapor 4.122.2 / Fluent 4.13.0 + fluent-postgres-driver 2.14.0 |
| Logging | LogLayer v3.0.0 + transport `log/slog` | SwiftLog bawaan Vapor |
| Image runtime | Distroless `static-debian13:nonroot` (atau Alpine) | Distroless `cc-debian13:nonroot` (atau Alpine/musl) |

Spesifikasi lengkap: [`docs/PRD.md`](docs/PRD.md) dan [`docs/ADR.md`](docs/ADR.md) (menang bila ada konflik dengan README ini).
**Hasil dibaca sebagai perbandingan relatif**: angka beban "Apple Silicon, Docker VM: hasil relatif, bukan absolut"; angka build time, DX, modular, dan profil "macOS native". Jangan dibandingkan dengan mesin lain.

## Syarat Mac

- Apple Silicon (arm64), macOS dengan Docker Desktop atau OrbStack; **VM Docker ≥ 8 vCPU dan ≥ 8 GB** (`make doctor` menolak bila kurang dan hanya menunjukkan cara mengubahnya; tidak mengubah pengaturan apa pun).
- Charger tersambung, Low Power Mode mati, aplikasi berat lain ditutup. Run beban dibungkus `caffeinate -dims`.
- Disk bebas ≥ 20 GiB (image Swift 4 GB, cache build, volume Postgres). Docker berhenti diam-diam bila disk penuh.
- Untuk `build-bench`, `profile`, `dx-bench`, `modular-bench`: **Go 1.27.2 dan Swift 6.4 native** (Xcode 27 atau toolchain swift.org). Bila tidak ada, `make doctor` menolak target itu dengan petunjuk; **tidak ada yang dipasang otomatis**. Bagian lain tetap bisa dibangun.
- GNU Make 3.81 (bawaan macOS) cukup; Python 3 untuk `tools/`.

## Cara menjalankan

```sh
make doctor                       # cek prasyarat
make db-up db-seed                # Postgres (port host 54322) + seed deterministik + checksum + template
make contract                     # gerbang kesetaraan: kontrak/golden, jumlah query, konfigurasi, logging, checksum
make bench-smoke                  # uji alur < 15 menit; angka berlabel 'smoke, bukan final'
make report                       # results/report.md, CSV, grafik

make bench APP=both SCENARIO=core # S1,S3,S4,S8 penuh (mencetak estimasi durasi; berjam-jam)
make bench SCENARIO=all           # S1..S11
make bench-tuned                  # S13: varian tuned + sapuan pool 8,16,32,64
make startup-bench                # S12: ukuran image, startup, request pertama, memori (kedua flavor)
make scale-bench                  # S14/SC1: 1,2,3 core
make build-bench                  # B1..B3 dev+release (native)      | BUILD_REPEATS, BUILD_CONFIG=dev|release|both
make profile APP=go SCENARIO=s8   # profil native pada 50% saturasi (juga APP=swift)
make dx-bench                     # DX1..DX5 (native)
make modular-bench                # M1/SC3: MODULES=1,5,20 (50 opsional)
make help                         # semua target dan variabel
```

Variabel: `APP=go|swift|both` `SCENARIO=s1,s3,..|core|all` `REPEATS=3` `PROFILE=mac-m2|linux-medium` `SLO_P99_MS=250` `LOG_MODE=quiet|access` `LOG_FORMAT=text|json` (Go) `VARIANT=default|tuned` `IMAGE_FLAVOR=distroless|alpine` `BUILD_REPEATS` `BUILD_CONFIG` `DURATION=45` `SCALE_CPUS=1,2,3` `MODULES=1,5,20`. Juga dibaca dari `.env` (lihat `.env.example`). Prioritas: baris perintah > `.env` > `profiles/<PROFILE>.conf` > `profiles/images.conf`.

Pengembangan: `make go-run` / `make swift-run` (native, butuh `db-up db-seed`), `make go-up` / `make swift-up` (container dengan batas profil; port dev 8080 Go, 8081 Swift, admin Go 6060), `make go-test` / `make swift-test` (suite paritas 52 kasus).

Jangan menjalankan `build-bench`, `dx-bench`, `modular-bench`, atau `profile` bersamaan dengan beban Docker. Target build menghentikan container `bench-*` yang sedang berjalan.

### Estimasi durasi benchmark penuh (profil mac-m2)

| Target | Perkiraan |
|---|---|
| `make bench-smoke` | ~12 menit |
| `make bench SCENARIO=core` (3 ulangan, 2 app) | ~3 jam (dicetak ulang oleh orkestrator dari konfigurasi) |
| `make bench SCENARIO=all` | ~7 jam, termasuk soak 20 menit |
| `make bench-tuned` | ~2,5 jam |
| `make scale-bench` | ~1,5 jam |
| `make startup-bench` | ~10 menit (10 ulangan x 2 stack x 2 flavor) |
| `make build-bench` (3/5/3 ulangan, dev+release) | ~1,5 jam |
| `make dx-bench` (3 ulangan) | ~1,5 jam |
| `make modular-bench` (1,5,20 modul) | ~2 jam |

## Struktur

```
docker-compose.yml / .dev.yml / .tuned.yml   postgres, go-app, swift-app, k6, probe, sampler (+ profil monitoring, mati)
profiles/  mac-m2.conf, linux-medium.conf, images.conf (image terkunci dengan digest)
db/        schema.sql, seed.sql, postgres.conf, checksums.txt, fixtures/
go-app/    cmd/server, internal/{domain,store,httpapi,platform}, Dockerfile(.alpine)
swift-app/ Sources/{Domain,Persistence,HTTPAPI,Platform,App}, Tests/ParityTests, Dockerfile(.alpine)
contract-tests/  cases.json, golden/, contract.py (gerbang), check_layout.py, parity-cases/cases.json (52 kasus bersama)
loadtest/  main.js, scenarios/s1..s9, lib/, data/ (ID hasil seed)
tools/     db.sh dc.sh doctor.sh bench.py runner.py sampler/ startup_bench.py profile.py buildtime/ dx/ modgen/ report/
tuning/variants.yaml   perubahan tuned + alasan + sumber + bukti
results/   raw/ profiles/ charts/ report.md *.csv   (di-gitignore)
```

Arsitektur setara dan satu arah (HTTP → Store → Domain; Platform dipakai dari atas; tanpa siklus), diperiksa oleh `make contract`.

## Status verifikasi (sesi pembuatan, 2026-10-13)

Semua target dijalankan **versi pendek** untuk membuktikan alurnya; benchmark penuh belum dijalankan (butuh berjam-jam). Angka dari run pendek tidak boleh dipakai sebagai hasil.

| Target | Yang dijalankan | Hasil |
|---|---|---|
| `make doctor` | semua pengecekan | 0 gagal; 1 peringatan di awal sesi (charger belum tersambung), 0 peringatan pada run akhir |
| `make contract` | `distroless` **dan** `IMAGE_FLAVOR=alpine` | **lulus** (34 kasus golden x 2 mode log x 2 app, query/request sama, pool 16, quiet 0 baris, access 1 baris/request, checksum cocok) |
| `make go-test` / `make swift-test` | suite paritas | 52 kasus lulus di kedua suite; himpunan ID identik (dicek `dx-bench`) |
| `make bench-smoke` | S1–S8, 1 ulangan | selesai **10 m 55 s** (< 15 menit); `report.md` terbentuk; berlabel smoke |
| `BENCH_SMOKE=1 make bench SCENARIO=s9,s10,s11` | S9, S10 (3 segmen x 5 s), S11 | berjalan (smoke) |
| `make bench-tuned` | `BENCH_SMOKE=1 TUNED_SCENARIOS=s3,s8 POOLS=8,32 SWEEP_SCENARIOS=s3` | berjalan; bukti varian di `tuning/variants.yaml` |
| `make scale-bench` | `BENCH_SMOKE=1`, CPU 1,2,3 | berjalan |
| `make startup-bench` | `STARTUP_REPEATS=2`, kedua flavor | berjalan; Swift Alpine (musl) terbukti berjalan |
| `make build-bench` | `BUILD_REPEATS=1`, dev+release | B1–B3 berjalan di kedua stack; hash binary B2 berubah; bukan ditolak doctor (Go 1.27.2 dan Swift 6.4 ada) |
| `make profile` | `APP=go` dan `APP=swift`, `DURATION=15 RATE=2000` | berjalan (pprof + SVG flame; `sample` + `xctrace`) |
| `make dx-bench` | `BUILD_REPEATS=1` | DX1–DX5 berjalan |
| `make modular-bench` | `MODULES=1,3 BUILD_REPEATS=1` | berjalan (T1/T2 x Go/Swift) |
| `make report` | semua data di atas | `results/report.md`, 5 CSV, 21 grafik (SVG+PNG); contoh smoke: [`results/examples/report-smoke.md`](results/examples/report-smoke.md) |

Variabel khusus uji singkat: `BENCH_SMOKE=1` (durasi pendek; `bench`, `bench-tuned`, `scale-bench`), `STARTUP_REPEATS`, `STARTUP_FLAVORS`, `TUNED_SCENARIOS`, `POOLS`, `SWEEP_SCENARIOS`.

**Belum dikerjakan / belum diuji**: benchmark penuh (`make bench`, `bench-tuned`, `scale-bench`, `build-bench`, `dx-bench`, `modular-bench` dengan ulangan default), profil `linux-medium`, profil `monitoring`, dan varian opsional `swift-app-v5` (Vapor 5 beta).

## Cara membaca hasil

`results/report.md` berisi: versi dan konfigurasi, **peringatan validitas**, tabel beban per skenario (tahap A: RPS dan p99 vs VU + titik saturasi; tahap B: p99, CPU user/sys, CPU-ms/req, memori, thread, FD, query/req pada laju tetap yang sama), S10/S11, build time, S12, tuned vs default, DX, skalabilitas, profil 10 teratas, dan **Kesimpulan** (matriks kriteria, rekomendasi kondisional, "Tidak diukur", batas).

- Sel `median [min–maks]`; ⚠ menandai CV > 5%.
- Stack hanya dinyatakan **lebih baik** bila rentang min–maks tidak tumpang tindih **dan** selisih median > 5%; selain itu "setara" atau "belum cukup bukti" (ulangan < 2).
- Resource hanya sebanding pada **laju tetap yang sama** (tahap B); pada saturasi (tahap A) angka menunjukkan kapasitas.
- Memori: kesimpulan memakai `anon` (memori privat); `memory.peak` cgroup ikut menghitung page cache berkas yang dibebankan ke cgroup pertama yang menyentuhnya sehingga tidak deterministik.
- Titik ditandai `k6_bound` (CPU k6 > 80%), `thermal_throttled`, `db_bound` (CPU Postgres ≥ 90%); run yang `k6_bound`/throttled diulang otomatis sampai 3 kali.
- Mentah: `results/raw/<run-id>/` (`points.jsonl`, `runs.jsonl`, `meta.json`, per run: `sampler.csv` per detik, `docker_stats.csv` pembanding silang, ringkasan k6, snapshot `pg_stat_*`).

## Lingkungan terverifikasi (Langkah 0, 2026-10-13)

| Item | Hasil |
|---|---|
| Mesin | arm64; Mac14,9 (M2 Pro) 10 core (6P+4E); 16 GiB; macOS 27.0.1 |
| Docker | server/klien 29.8.2, engine **OrbStack** (diizinkan PRD), compose v5.5.0; VM 10 vCPU, 8.392.605.696 B (8003 MiB); cgroup v2 |
| Make | GNU Make 3.81 (Makefile berjalan di sini) |
| Toolchain native | `go1.27.2 darwin/arm64`; Swift 6.4 (`swiftlang-6.4.0.34.1`); Xcode di `/Applications/Xcode.app`; `xctrace` ada |
| Image (semua linux/arm64, terkunci digest di `profiles/images.conf`) | `golang:1.27.2`, `swift:6.4-noble`, `gcr.io/distroless/static-debian13:nonroot`, `gcr.io/distroless/cc-debian13:nonroot`, `alpine:3.24.2`, `postgres:18.6-alpine`, `grafana/k6` **v2.3.0** |
| Modul Go | chi v5.3.2 (v5.4.0 ada; dipilih seri 5.3.x sesuai spesifikasi), gorm v1.31.2, driver/postgres v1.6.3, go.loglayer.dev/{v3, transports/slog/v3, integrations/loghttp/v3} v3.0.0 |
| Paket Swift | Vapor 4.122.2, Fluent 4.13.0, fluent-postgres-driver 2.14.0 (dikunci di `Package.resolved`) |
| Opsi SwiftPM | `--scratch-path`, `--cache-path`, `--config-path`, `--security-path` diterima `swift build` dan `swift package resolve` (terbukti oleh `build-bench`) |
| `--static-swift-stdlib` | **Linux: dipakai. macOS: TIDAK didukung** (flag diterima tetapi compiler memperingatkan "no longer supports statically linking"; `otool -L` menunjukkan `libswiftCore.dylib` dinamis) → build release native tanpa flag itu |
| Compilation caching SwiftPM | tidak ada flag di `swift build --help`; tidak aktif |
| `GOCACHE`/`GOMODCACHE` terisolasi | bekerja (B1 mengunduh dari nol ke direktori `*.noindex`) |
| Sampler | container `pid=host` + `cgroupns=host` membaca `/sys/fs/cgroup/docker/<id>/{cpu.stat,memory.*,pids.current,io.stat}` dan `/proc/<pid>` container lain, **tanpa** `--privileged`; fallback `docker stats` tetap tersedia |
| Base image | binary Go jalan di Distroless static dan Alpine; binary Swift (`--static-swift-stdlib`, glibc) jalan di Distroless cc; flavor Alpine Swift memakai Static Linux SDK **musl** (**label musl**: alokator musl berbeda dari glibc, hasil tidak sebanding langsung) dan terbukti berjalan |
| Postgres | 18.6; `pg_stat_statements` aktif (`track=top`), `shared_buffers=512MB`, `synchronous_commit=off` (fsync on), `max_connections=200`, data di named volume |

## Asumsi

1. Direktori kerja adalah `go-vs-swift/` (bukan `bench-go-vs-swift/`). PRD dan ADR sudah ada di direktori itu dan dipindahkan ke `docs/`.
2. Port Postgres di host **54322** (permintaan pengguna; port 5432 dipakai proyek lain di mesin ini). Antar container tetap 5432.
3. Aplikasi memakai DB `bench`; template `bench_tpl` (reset: `DROP DATABASE bench` + `CREATE DATABASE bench TEMPLATE bench_tpl`). Uji kontrak memakai DB `fixture` (+ `fixture_tpl`).
4. Fixture (20 user, 100 order) dihasilkan **sekali** oleh skrip sekali-pakai dengan nilai literal tetap, lalu di-commit sebagai `db/fixtures/fixture.sql` statis (user 17–20 tanpa order, semua status, 14 note kosong, order 50 dengan note 200 karakter, pasangan `created_at` kembar untuk uji tie-break). Golden JSON direkam dari Go lalu **diverifikasi terhadap SQL independen** dan diuji di kedua aplikasi.
5. Seed memakai `md5` sebagai fungsi hash deterministik; `loadtest/data`: semua 10.000 user, order ber-id kelipatan 10 (50.000), semua order `pending` (99.845). Distribusi terukur: 20/50/20/10%, maks 219 order per user, rata-rata 50.
6. `orders.note` `NOT NULL DEFAULT ''`. Detail kontrak yang tidak ditetapkan spesifikasi: `GET /users/{id}/orders` mengembalikan array JSON (kosong untuk user tak dikenal, 1 query), `?limit` 1..100 (default 20); `include=orders` menambah kunci `orders`; `POST /orders/{id}/pay` mengembalikan `{order, payment}`; id tidak valid → 400 `invalid id`; galat DB (termasuk pelanggaran FK) → 500 `{"error":"internal error"}`; kunci JSON yang hilang diperlakukan sebagai nilai nol di kedua sisi (decode longgar). Perilaku metode HTTP salah (chi 405 vs Vapor 404) tidak termasuk kontrak.
7. `pg_stat_statements.track = top`: hanya statement yang dikirim klien dihitung; query internal FK (`SELECT … FOR KEY SHARE`) bukan query aplikasi. `BEGIN/COMMIT/ROLLBACK` ikut dihitung (transaksi `pay` = 5 eksekusi di kedua stack).
8. GORM `SkipDefaultTransaction: true` agar satu statement tidak dibungkus `BEGIN/COMMIT` (Fluent tidak melakukannya) — dipakai di kedua mode, bukan tuning. Logger GORM `Silent`; galat DB tetap dicatat handler lewat `loghttp` sehingga hanya satu jalur log (LogLayer) dan mode quiet tidak menulis baris.
9. Eager loading (S5): Fluent `with` tidak mendukung ORDER BY, jadi urutan `created_at DESC, id DESC` diterapkan **di memori pada kedua sisi** (GORM `Preload` polos).
10. Fragmen string GORM (`Where("user_id = ?")`, `Order("created_at DESC, id DESC")`) dianggap API ORM idiomatik, bukan SQL mentah.
11. Dependensi antar lapisan: antarmuka repositori didefinisikan di lapisan Store/Persistence dan dipakai HTTP (HTTP → Store → Domain); fake repository di test mengimplementasikannya.
12. Tahap A: satu skenario k6 `constant-vus` selama ramp+steady; `phase=steady` di-tag per request (setelah `RAMP_S`) dan RPS dihitung `count steady / detik steady`; jendela sampler diambil dari jam VM (`Date.now()` k6 di VM yang sama dengan sampler). Satu **run** = restart + reset DB + reset statistik + warm-up + semua titik tahap itu; tahap B memakai 25/50/75% saturasi (median antar ulangan) implementasi yang lebih lambat.
13. Smoke (`bench-smoke`): 1 ulangan, warm-up 3 s, VU 32 dan 128 (1 s ramp + 4 s steady), tahap B 50% selama 5 s, skenario S1–S8.
14. Startup (S12): waktu = `Created` container → /healthz 200 pertama (probe Go di jaringan yang sama, polling 10 ms; kedua cap waktu dari jam VM). Memori idle diukur setelah 4 request pertama (urutan latensi pertama) lalu setelah 100 request; dilaporkan `anon` dan `memory.current`.
15. DX2: "cache kosong" = cache build kosong dengan dependency sudah diunduh (agar jaringan tidak ikut terukur). DX1: Postgres idle berjalan; Go membuka koneksi DB saat start (ping GORM), Vapor membuka koneksi malas — perilaku default masing-masing. Framework test Swift: **Swift Testing**.
16. Varian tuned: `GOGC=400` (PRD memberi contoh 200); `GOMEMLIMIT` = 80% `APP_MEM`.
17. Profil `linux-medium` butuh ≥ 12 vCPU; `make doctor` menolaknya di VM lebih kecil.

## Deviasi

1. **Docker adalah OrbStack**, bukan Docker Desktop (PRD membolehkan). VM 10 vCPU / 8003 MiB (≥ 8 vCPU dan ≥ 8 GB desimal; di bawah 8 GiB biner). `cpuset` memakai vCPU 0–6 (app 0–1, Postgres 2–3, k6 4–5, sampler/probe 6).
2. **Berkas profil memakai ekstensi `.conf`**, bukan `.env`: pengaturan izin menolak pembuatan berkas `*.env`.
3. **Build Linux Swift memakai `--build-system native` (deprecated) dan `strip`**: pada Swift 6.4 Linux, Swift Build (default) gagal link dengan `--static-swift-stdlib` (`undefined reference` ke `_FoundationICU`/`_FoundationCollections`/CoreFoundation); sistem native berhasil. `strip` setara `-ldflags='-s -w'` Go. Berlaku untuk flavor Distroless dan Alpine.
4. **Prepared statement tidak setara secara mekanis**: Go memakai statement bernama yang di-cache (`execute stmt_…`); Fluent/PostgresNIO memakai extended protocol dengan statement **tanpa nama** (`execute <unnamed>`, parse per eksekusi) dan tidak mengekspos cache statement. Spesifikasi menyuruh memakai default PostgresNIO dan memverifikasinya; perbedaan ini ikut terukur dan dicatat sebagai peringatan validitas di laporan (`make contract` membuktikan keduanya extended protocol dari log Postgres).
5. **Graphviz tidak terpasang** (dan tidak dipasang): `go tool pprof -svg` tidak tersedia. SVG profil Go adalah flame graph buatan `tools/lib/flame.py` dari `pprof -traces`; `.pb.gz` tetap dari pprof. Grafik laporan dibuat sebagai SVG oleh `tools/report/svgchart.py` (tanpa matplotlib) lalu dikonversi ke PNG dengan `qlmanage` bawaan macOS bila ada.
6. **`sample` Swift** menyampel semua thread; 10 teratas mentah didominasi primitif tunggu kernel. `top10.json` menyimpan daftar mentah **dan** daftar tanpa primitif tunggu (nama yang disaring dicantumkan). `xctrace` Time Profiler juga direkam.
7. **Varian tuned**: `-Xswiftc -lto=llvm-thin` diuji dan **dibuang** (link gagal: `undefined symbol` Concurrency/Dispatch dengan `--static-swift-stdlib`). Flag yang dipakai, `-Xswiftc -cross-module-optimization`, terbukti tersedia (daftar `swiftc -frontend -help-hidden`) dan image tuned terbangun/berjalan, tetapi dokumentasi online-nya **tidak terverifikasi** (URL GitHub 404) — diberi label di `tuning/variants.yaml`. PGO memakai profil dari `make profile APP=go` (`go-app/pgo/default.pgo`, di-commit).
8. **Tools HTTP**: `curl` ditolak oleh pengaturan izin sesi ini, sehingga semua uji HTTP manual dilakukan lewat runner Python (`contract-tests/contract.py`, `tools/lib/benchenv.py`).
9. `--summary-export` k6 dipertahankan; waktu mulai tes diekspor sebagai metrik gauge kustom `bench_test_start_ms` agar jendela steady bisa dipotong dari sampler (busybox `date` tidak mendukung nanodetik).
10. Hanya satu pemicu `docker compose` yang memakai nama profil `apps`/`tools`; profil `monitoring` (cAdvisor, Prometheus, Grafana) tersedia tetapi tidak diuji.
11. Opsional `swift-app-v5` (Vapor 5 beta) **tidak dikerjakan** (opsional, di luar sesi ini).

## Batasan interpretasi

- Hasil berlaku untuk MacBook Pro M2 Pro (laptop), versi terkunci, dan beban yang diuji; bukan klaim umum tentang bahasa atau server.
- `synchronous_commit=off` dan dataset yang muat di RAM Postgres: biaya tulis dan I/O lebih rendah dari produksi.
- Perbedaan di bawah variasi antar ulangan (CV > 5% ditandai) bukan selisih nyata. Penyebab selisih tidak disimpulkan tanpa data profil atau dokumentasi yang dikutip; profil native macOS tidak sebanding absolut dengan hasil container.
- Skala vertikal hanya 1–3 core; M1 memakai kode sintetis dan hanya N yang diuji.
