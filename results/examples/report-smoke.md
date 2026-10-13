> **Contoh laporan dari run smoke/uji singkat (angka smoke, bukan final).** Dihasilkan oleh `make report` pada 2026-10-13; grafik yang dirujuk ada di `results/charts/` (tidak di-commit).

# Laporan benchmark Go vs Swift

_Dibuat 2026-10-13 07:28:53 oleh `tools/report/report.py`. Semua angka berasal dari run nyata di `results/raw/`._

> **Label.** Angka beban: **Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut**. Angka build time, DX, modular, dan profil: **macOS native**. Hasil tidak boleh dibandingkan dengan mesin lain.

## Versi, konfigurasi, dan checksum seed

| Item | Nilai |
|---|---|
| Go | 1.27.2 (image golang:1.27.2; chi v5.3.2, gorm v1.31.2, driver/postgres v1.6.3, loglayer v3.0.0) |
| Swift | 6.4.0 (image swift:6.4-noble; Vapor 4.122.2, Fluent 4.13.0, fluent-postgres-driver 2.14.0) |
| k6 | k6 v2.3.0 (commit/e088784614, go1.27.1, linux/arm64) |
| Postgres | postgres (PostgreSQL) 18.6 |
| Mac | Mac14,9, macOS 27.0.1 (26A434), 10 core (6P+4E) |
| Docker | 29.8.2 (OrbStack); VM 10 vCPU, 7.82 GiB; cgroup v2 |
| Profil / flavor / varian | mac-m2 / distroless / default; SLO p99 250 ms |
| Batas | {"APP_CPUS": "2", "APP_CPUSET": "0-1", "APP_MEM": "1g", "PG_CPUS": "2", "PG_CPUSET": "2-3", "PG_MEM": "2g", "K6_CPUS": "2", "K6_CPUSET": "4-5", "K6_MEM": "1g", "DB_POOL_TOTAL": "16", "EVENT_LOOPS": "2"} |
| ulimit -n | 1048576 |
| image GO_BUILD_IMAGE | `golang:1.27.2@sha256:5bc7f572bbaa98885a3a1fd9c0aa76b59e3e14e8628bfc316bbfd0c701e4818c` |
| image SWIFT_BUILD_IMAGE | `swift:6.4-noble@sha256:31d14d727f4451f25e29bac9c42563a098c39ac66415e8bad970f48038e38aca` |
| image DISTROLESS_STATIC_IMAGE | `gcr.io/distroless/static-debian13:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3` |
| image DISTROLESS_CC_IMAGE | `gcr.io/distroless/cc-debian13:nonroot@sha256:e792ab3d241a468a4fd7519ddbbebe66b49b5f365771716ea688ad40b6c6f1c2` |
| image ALPINE_IMAGE | `alpine@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6` |
| image PG_IMAGE | `postgres@sha256:77f585114c32fbca283dc835b0596f4e52b51b4c6662d7810b2f4084f60a1873` |
| image K6_IMAGE | `grafana/k6@sha256:e66db15b860113878fa74670e31f5e274830b7b6e42c8bff28b2f2d86a257603` |
| thermal sebelum | CPU_Speed_Limit=100 |
| Checksum seed (tabel, baris, md5) | `users 10000 f77f30a44e3e6275d2fcb8ac9c4723ac`<br>`orders 500000 af19166beba09ff776d84cb246f3370e`<br>`payments 0 empty` |

**Gerbang kesetaraan (make contract)**: LULUS; protokol: {"go": {"kind": "extended/named-prepared", "execs_seen": 6}, "swift": {"kind": "extended/unnamed", "execs_seen": 6}}.

## Peringatan validitas

- Ada run **smoke** (1 ulangan, durasi dipangkas): angka smoke diberi label 'smoke, bukan final' dan tidak dipakai untuk kesimpulan.
- **Prepared statement tidak setara secara mekanis**: Go (GORM `PrepareStmt`) memakai statement bernama yang di-cache; Fluent/PostgresNIO memakai extended protocol dengan statement tanpa nama (parse per eksekusi) dan tidak mengekspos cache statement. Kedua sisi memakai extended protocol (bukti log Postgres, `make contract`); perbedaannya adalah perilaku default stack dan ikut terukur.
- Fluent `with` tidak mendukung ORDER BY pada eager load; urutan (created_at DESC, id DESC) diterapkan di memori pada **kedua** sisi agar pekerjaan setara (S5).
- GORM `SkipDefaultTransaction: true` dipakai agar jumlah query per request sama dengan Fluent (BEGIN/COMMIT tidak ditambahkan GORM pada satu statement).
- Timestamp baris baru: Go mencetak presisi mikrodetik, Vapor `.iso8601` presisi detik; kontrak menormalkan timestamp dinamis (data fixture identik).
- Build Linux Swift memakai `--build-system native` (deprecated) karena Swift Build default gagal link dengan `--static-swift-stdlib` di Swift 6.4 Linux; binary di-`strip` (setara `-s -w` Go). Lihat README > Deviasi.
- Hanya pengukuran beban memakai container; build time, DX, modular, dan profil adalah **macOS native** dan tidak boleh dicampur dengan angka beban.
- `--static-swift-stdlib` tidak didukung di macOS: build release Swift native tanpa flag itu.
- 1 titik ditandai `gave_up_after_retries`
- 1 titik ditandai `k6_bound`

Hasil tidak boleh dibandingkan dengan mesin lain. Perbedaan di bawah variasi antar ulangan (CV > 5% ditandai ⚠) tidak boleh dibaca sebagai selisih nyata.

## Hasil beban (default)

> **Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut.** Sumber: angka SMOKE, BUKAN FINAL. Run: 20261013-064730-bench-smoke, 20261013-071419-bench-smoke.
> **Definisi memori.** `anon` = memori privat proses (stabil, dipakai untuk kesimpulan); `cgroup peak` = `memory.peak` yang ikut menghitung page cache berkas yang dibebankan ke cgroup pertama yang menyentuhnya, sehingga tidak deterministik antar run.
> **Angka smoke, bukan final:** 1 ulangan, durasi dipangkas; tidak ada kesimpulan yang lolos aturan (butuh ≥ 2 ulangan).

### S1 GET /bench/json

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 32879 | 5.8 | 0.0000 | 38778 | 4.7 | 0.0000 |
| 128 | 37348 | 15.2 | 0.0000 | 37999 | 16.7 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 37348, Swift 38778; rasio Swift/Go 1.04× [1.04–1.04] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.80, Swift 0.79. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (18674 RPS) | go | 0.75 | 21.02 | 0.53 | 0.36 / 0.16 | 0.015 | 14 / 15 | 8 | 253 | 0.00 | 6535 |
| 50% (18674 RPS) | swift | 0.36 | 18.38 | 0.73 | 0.60 / 0.13 | 0.020 | 5 / 12 | 6 | 251 | 0.00 | 4349 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 45729 | 3661438 / 1406910 | 0.011 | 0.00 |
| swift | 128 | 26489 | 8730245 / 642783 | 0.019 | 0.00 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 1.18× [1.18–1.18]; VU 128: 1.02× [1.02–1.02]

### S2 POST /bench/echo

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 26957 | 5.9 | 0.0000 | 23832 | 5.1 | 0.0000 |
| 128 | 36138 | 16.2 | 0.0000 | 21673 | 23.0 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 26957, Swift 23832; rasio Swift/Go 0.88× [0.88–0.88] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.81, Swift 0.56. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (11916 RPS) | go | 0.55 | 14.27 | 0.54 | 0.41 / 0.13 | 0.023 | 11 / 14 | 8 | 155 | 0.00 | 1611 |
| 50% (11916 RPS) | swift | 0.32 | 9.05 | 1.19 | 1.03 / 0.15 | 0.050 | 5 / 60 | 8 | 145 | 0.00 | 818 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 34337 | 3517796 / 1308665 | 0.015 | 0.00 |
| swift | 128 | 12280 | 3862347 / 1677447 | 0.041 | 0.00 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.88× [0.88–0.88]; VU 128: 0.60× [0.60–0.60]

### S3 GET /users/{id}

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 25496 | 6.2 | 0.0000 | 10824 | 8.3 | 0.0000 |
| 128 | 26777 | 19.3 | 0.0000 | 11586 | 21.7 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 26777, Swift 11586; rasio Swift/Go 0.43× [0.43–0.43] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.68, Swift 0.36. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (5793 RPS) | go | 0.23 | 5.32 | 0.38 | 0.26 / 0.12 | 0.033 | 12 / 15 | 8 | 81 | 1.00 | 7 |
| 50% (5793 RPS) | swift | 0.65 | 20.94 | 1.37 | 1.18 / 0.19 | 0.121 | 5 / 6 | 8 | 100 | 1.00 | 527 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 21323 | 1622614 / 1183715 | 0.023 | 0.39 |
| swift | 128 | 5994 | 1621500 / 181123 | 0.083 | 0.35 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.42× [0.42–0.42]; VU 128: 0.43× [0.43–0.43]

### S4 GET /users/{id}/orders

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 15841 | 8.4 | 0.0000 | 2766 | 19.4 | 0.0000 |
| 128 | 18192 | 28.2 | 0.0000 | 2726 | 84.2 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 18192, Swift 2766; rasio Swift/Go 0.15× [0.15–0.15] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.51, Swift 0.10. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (1383 RPS) | go | 0.63 | 6.80 | 0.38 | 0.30 / 0.07 | 0.142 | 11 / 15 | 8 | 75 | 1.00 | 216 |
| 50% (1383 RPS) | swift | 1.04 | 34.10 | 0.97 | 0.92 / 0.05 | 0.352 | 6 / 12 | 8 | 81 | 1.00 | 26 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 11188 | 1017507 / 499273 | 0.045 | 0.48 |
| swift | 128 | 1368 | 294049 / 283098 | 0.365 | 0.15 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.17× [0.17–0.17]; VU 128: 0.15× [0.15–0.15]

### S5 GET /users/{id}?include=orders

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 6074 | 18.8 | 0.0000 | 1264 | 38.8 | 0.0000 |
| 128 | 8035 | 47.4 | 0.0000 | 1322 | 139.1 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 8035, Swift 1322; rasio Swift/Go 0.16× [0.16–0.16] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.26, Swift 0.04. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (661 RPS) | go | 0.98 | 6.68 | 0.36 | 0.28 / 0.08 | 0.268 | 12 / 17 | 8 | 74 | 2.00 | 0 |
| 50% (661 RPS) | swift | 2.02 | 4.90 | 1.02 | 0.97 / 0.05 | 0.769 | 8 / 61 | 8 | 81 | 2.00 | 0 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 4765 | 386695 / 290288 | 0.105 | 0.41 |
| swift | 128 | 662 | 107093 / 74288 | 0.755 | 0.11 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.21× [0.21–0.21]; VU 128: 0.16× [0.16–0.16]

### S6 POST /orders

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 21922 | 7.0 | 0.0000 | 9316 | 6.8 | 0.0000 |
| 128 | 23379 | 22.2 | 0.0000 | 9677 | 24.0 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 23379, Swift 9677; rasio Swift/Go 0.41× [0.41–0.41] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.70, Swift 0.32. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (4839 RPS) | go | 0.23 | 4.29 | 0.32 | 0.21 / 0.10 | 0.033 | 12 / 30 | 8 | 74 | 1.00 | 0 |
| 50% (4839 RPS) | swift | 0.58 | 4.18 | 1.27 | 1.14 / 0.14 | 0.132 | 5 / 10 | 8 | 82 | 1.00 | 4 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 21129 | 1326537 / 720927 | 0.024 | 0.50 |
| swift | 128 | 4920 | 1345800 / 636755 | 0.102 | 0.29 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.42× [0.42–0.42]; VU 128: 0.41× [0.41–0.41]

### S7 PUT /orders/{id}

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 18011 | 7.8 | 0.0000 | 6005 | 8.9 | 0.0000 |
| 128 | 18341 | 24.8 | 0.0000 | 6095 | 29.4 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 18341, Swift 6095; rasio Swift/Go 0.33× [0.33–0.33] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.51, Swift 0.20. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (3048 RPS) | go | 0.34 | 3.98 | 0.31 | 0.20 / 0.10 | 0.051 | 12 / 30 | 8 | 74 | 2.00 | 0 |
| 50% (3048 RPS) | swift | 0.81 | 3.12 | 1.22 | 1.09 / 0.13 | 0.200 | 5 / 62 | 8 | 81 | 2.00 | 0 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 16336 | 1067033 / 881241 | 0.031 | 0.58 |
| swift | 128 | 3119 | 820664 / 98949 | 0.160 | 0.35 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.33× [0.33–0.33]; VU 128: 0.33× [0.33–0.33]

### S8 campuran

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 16412 | 8.7 | 0.0000 | 4716 | 15.8 | 0.0000 |
| 128 | 20171 | 25.6 | 0.0000 | 4802 | 54.3 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 20171, Swift 4802; rasio Swift/Go 0.24× [0.24–0.24] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.57, Swift 0.14. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (2401 RPS) | go | 0.45 | 4.92 | 0.37 | 0.28 / 0.09 | 0.077 | 13 / 31 | 9 | 74 | 1.20 | 0 |
| 50% (2401 RPS) | swift | 0.99 | 4.81 | 1.12 | 1.03 / 0.09 | 0.234 | 6 / 7 | 8 | 81 | 1.20 | 0 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 13174 | 1063925 / 902031 | 0.038 | 0.46 |
| swift | 128 | 2403 | 487321 / 449875 | 0.208 | 0.20 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.29× [0.29–0.29]; VU 128: 0.24× [0.24–0.24]

### S9 POST /orders/{id}/pay

**Tahap A (tangga konkurensi, closed-loop)** — RPS dan p99 (ms): median [min–max]

| VU | Go RPS | Go p99 ms | Go err maks | Swift RPS | Swift p99 ms | Swift err maks |
|---|---|---|---|---|---|---|
| 32 | 7123 | 12.6 | 0.0000 | 3789 | 12.2 | 0.0000 |
| 128 | 6982 | 74.3 | 0.0000 | 3788 | 41.0 | 0.0000 |

**Titik saturasi** (RPS tertinggi dengan error < 0,1% dan p99 < SLO): Go 7123, Swift 3789; rasio Swift/Go 0.53× [0.53–0.53] → belum cukup bukti (ulangan < 2)

Utilisasi CPU k6 pada VU tertinggi (batas validitas 0,8; di atasnya run dibuang): Go 0.25, Swift 0.13. Bila angka mendekati 0,8, saturasi bisa dibatasi pembangkit beban (khususnya S1/S2 yang tanpa database).

**Tahap B (laju tetap, open-loop; resource sebanding pada throughput yang sama)**

| Laju (% saturasi yang lebih lambat) | App | p50 ms | p99 ms | CPU core | CPU user / sys | CPU-ms/req | Mem anon maks / cgroup peak MB | Thread maks | FD maks | Query/req | Dropped |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 50% (1894 RPS) | go | 0.80 | 7.68 | 0.51 | 0.30 / 0.21 | 0.134 | 12 / 29 | 8 | 76 | 5.00 | 16 |
| 50% (1894 RPS) | swift | 1.38 | 3.26 | 1.31 | 1.13 / 0.19 | 0.346 | 5 / 5 | 8 | 81 | 5.00 | 0 |

**Efisiensi pada VU tertinggi (kapasitas, bukan perbandingan efisiensi — lihat tahap B)**

| App | VU | RPS per core terpakai | RPS per GB mem (anon maks / cgroup peak) | CPU-ms/req | Util. Postgres |
|---|---|---|---|---|---|
| go | 128 | 6339 | 393413 / 312848 | 0.079 | 0.80 |
| swift | 128 | 1913 | 563811 / 60353 | 0.261 | 0.38 |

Rasio RPS Swift/Go (median [rentang konservatif]): VU 32: 0.53× [0.53–0.53]; VU 128: 0.54× [0.54–0.54]

## S10 soak (S8 pada 70% saturasi)

Segmen berurutan tanpa restart; drift p99 dan pertumbuhan memori per segmen (median antar ulangan). **Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut**

| App | Segmen | p99 ms segmen pertama | p99 ms segmen terakhir | Mem anon MB awal | Mem anon MB akhir | Thread akhir |
|---|---|---|---|---|---|---|
| go | 3 | 5.11 | 5.15 | 12.5 | 12.7 | 8 |
| swift | 3 | 8.22 | 8.39 | 6.3 | 6.4 | 8 |

## S11 biaya logging (S8 pada laju tetap 50% saturasi: quiet vs access)

| App | CPU-ms/req quiet | CPU-ms/req access | Δ CPU-ms/req | p99 quiet ms | p99 access ms | Δ p99 ms | Baris log/req | Byte log/req |
|---|---|---|---|---|---|---|---|---|
| go | 0.090 | 0.082 | -0.008 | 10.86 | 8.47 | -2.39 | 1.00 | 167 |
| swift | 0.283 | 0.299 | +0.016 | 21.63 | 28.09 | +6.45 | 1.00 | 77 |

Catatan: handler log Vapor pada mode access lebih ringkas daripada baris `loghttp` (ADR-004); selisih format dinyatakan, bukan disamarkan.

## Build time (B1–B3) — macOS native

Run: `20261013-060533`. hw.ncpu=10, Mac14,9, macOS 27.0.1. Ulangan: {'b1': 1, 'b2': 1, 'b3': 1}. Cache terisolasi (*.noindex), cache global tidak disentuh; paralelisme default toolchain (tanpa -j). Peak RSS = proses terbesar di pohon proses.

Verifikasi toolchain: opsi SwiftPM `--scratch-path/--cache-path/--config-path/--security-path` diterima: **True**; `--static-swift-stdlib` di macOS: **TIDAK didukung (release native tanpa flag ini)**; compilation caching SwiftPM aktif: **False**.

| Skenario | Konfigurasi | Fase | Stack | Wall s | CPU user+sys s | Peak RSS MB | Paralelisme efektif | Binary MB |
|---|---|---|---|---|---|---|---|---|
| B1 | dev | download | go | 1.34 | 0.8 | 30 | 0.59 | – |
| B1 | dev | download | swift | 19.75 | 39.2 | 124 | 1.99 | – |
| B1 | dev | compile | go | 10.08 | 45.7 | 496 | 4.53 | 22.1 |
| B1 | dev | compile | swift | 67.66 | 504.1 | 1281 | 7.45 | 69.8 |
| B1 | dev | total | go | 11.42 | 46.5 | 496 | 4.07 | 22.1 |
| B1 | dev | total | swift | 87.41 | 543.4 | 1281 | 6.22 | 69.8 |
| B2 | dev | build | go | 0.59 | 1.6 | 304 | 2.71 | 22.1 |
| B2 | dev | build | swift | 5.63 | 6.9 | 513 | 1.23 | 69.8 |
| B3 | dev | build | go | 9.67 | 45.1 | 485 | 4.67 | 22.1 |
| B3 | dev | build | swift | 63.30 | 486.4 | 1574 | 7.68 | 69.8 |
| B1 | release | download | go | 0.93 | 0.8 | 30 | 0.89 | – |
| B1 | release | download | swift | 17.97 | 39.2 | 124 | 2.18 | – |
| B1 | release | compile | go | 10.11 | 45.1 | 491 | 4.46 | 15.0 |
| B1 | release | compile | swift | 123.62 | 596.9 | 1792 | 4.83 | 51.3 |
| B1 | release | total | go | 11.04 | 45.9 | 491 | 4.16 | 15.0 |
| B1 | release | total | swift | 141.59 | 636.2 | 1792 | 4.49 | 51.3 |
| B2 | release | build | go | 0.44 | 1.3 | 246 | 3.02 | 15.0 |
| B2 | release | build | swift | 8.74 | 10.2 | 895 | 1.17 | 51.3 |
| B3 | release | build | go | 9.10 | 44.5 | 477 | 4.89 | 15.0 |
| B3 | release | build | swift | 115.52 | 572.4 | 1892 | 4.95 | 51.3 |

B1 dilaporkan sebagai total dan rincian unduh vs kompilasi; perbandingan utama memakai bagian kompilasi (unduhan bergantung jaringan).

## S12 ukuran image, startup, dan request pertama — Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut

Run: `20261013-070909`. **Waktu start mencakup overhead Docker yang sama untuk kedua stack** (create + start container + jaringan; diukur dari `Created` sampai /healthz 200 pertama dengan polling 10 ms dari container probe di jaringan yang sama, kedua cap waktu dari jam VM). Hanya selisih antar stack yang bermakna.

| Image | Flavor | Ukuran MB | Layer | Binary MB | User | Arch |
|---|---|---|---|---|---|---|
| bench-go:distroless | distroless | 16.9 | 14 | 14.6 | 65532:65532 | arm64 |
| bench-swift:distroless | distroless | 122.8 | 22 | 86.4 | 65532:65532 | arm64 |
| bench-go:alpine | alpine | 22.9 | 3 | 14.6 | 10001:10001 | arm64 |
| bench-swift:alpine | alpine | 84.0 | 3 | 75.7 | 10001:10001 | arm64 |


| Flavor | App | n | Start ms (create→/healthz 200) | Req pertama S1 ms | S3 ms | S4 ms | S6 ms | Mem anon 5 dtk setelah siap MB | Mem anon setelah 100 req MB | memory.current setelah 100 req MB (termasuk page cache) |
|---|---|---|---|---|---|---|---|---|---|---|
| alpine | go | 2 | 209 [209–209] | 0.7 [0.7–0.8] ⚠CV13% | 1.4 [1.3–1.5] ⚠CV12% | 1.1 [0.9–1.2] ⚠CV16% | 0.6 [0.5–0.7] ⚠CV22% | 3.3 [3.3–3.4] | 5.4 [5.4–5.4] | 5.7 [5.6–5.8] |
| alpine | swift | 2 | 212 [196–228] ⚠CV11% | 1.5 [1.5–1.5] | 9.9 [9.4–10.4] ⚠CV7% | 2.5 [2.4–2.7] ⚠CV9% | 1.2 [1.2–1.3] ⚠CV8% | 25.0 [24.9–25.0] | 23.0 [22.1–23.9] ⚠CV6% | 46.1 [29.6–62.7] ⚠CV51% |
| distroless | go | 2 | 226 [223–228] | 0.7 [0.7–0.8] | 1.9 [1.7–2.1] ⚠CV15% | 1.2 [1.2–1.3] ⚠CV6% | 0.7 [0.7–0.7] | 3.3 [3.3–3.3] | 5.3 [5.3–5.3] | 5.7 [5.6–5.7] |
| distroless | swift | 2 | 249 [206–293] ⚠CV25% | 1.1 [1.0–1.2] ⚠CV14% | 9.0 [9.0–9.1] | 2.3 [2.1–2.4] ⚠CV8% | 1.2 [1.1–1.3] ⚠CV10% | 3.5 [3.5–3.5] | 3.5 [3.5–3.5] | 32.6 [3.9–61.3] ⚠CV125% |

## S13 varian tuned (dilaporkan TERPISAH; kesimpulan utama hanya dari default)

**Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut.** Perubahan, alasan, sumber dokumentasi, dan bukti verifikasi: `tuning/variants.yaml`. Laju tahap B tuned = laju default (resource sebanding).

| Skenario | App | Metrik | Default | Tuned | Selisih median |
|---|---|---|---|---|---|
| S3 | go | saturasi RPS (A) | 26777.00 | 32567.00 | +21.6% |
| S3 | go | p99 ms @50% (B) | 5.32 | 7.57 | +42.2% |
| S3 | go | CPU-ms/req @50% (B) | 0.03 | 0.03 | -20.5% |
| S3 | go | mem anon maks MB @50% (B) | 11.88 | 22.38 | +88.5% |
| S3 | swift | saturasi RPS (A) | 11585.50 | 12762.50 | +10.2% |
| S3 | swift | p99 ms @50% (B) | 20.94 | 3.47 | -83.4% |
| S3 | swift | CPU-ms/req @50% (B) | 0.12 | 0.10 | -14.4% |
| S3 | swift | mem anon maks MB @50% (B) | 4.81 | 5.60 | +16.4% |
| S8 | go | saturasi RPS (A) | 20171.00 | 24853.00 | +23.2% |
| S8 | go | p99 ms @50% (B) | 4.92 | 2.76 | -44.0% |
| S8 | go | CPU-ms/req @50% (B) | 0.08 | 0.07 | -7.9% |
| S8 | go | mem anon maks MB @50% (B) | 12.67 | 23.21 | +83.3% |
| S8 | swift | saturasi RPS (A) | 4801.75 | 4509.25 | -6.1% |
| S8 | swift | p99 ms @50% (B) | 4.81 | 22.80 | +373.7% |
| S8 | swift | CPU-ms/req @50% (B) | 0.23 | 0.25 | +8.4% |
| S8 | swift | mem anon maks MB @50% (B) | 6.49 | 7.08 | +9.0% |

### Sapuan ukuran pool koneksi total (default; sama untuk kedua stack; tahap A)

| Skenario | App | Pool total | RPS puncak (median) | p99 ms pada RPS puncak | CPU core |
|---|---|---|---|---|---|
| S3 | go | 8 | 24784 | 23.1 | 1.05 [0.94–1.16] ⚠CV15% |
| S3 | go | 32 | 29762 | 18.8 | 1.21 [1.11–1.30] ⚠CV11% |
| S3 | swift | 8 | 12268 | 21.1 | 1.92 [1.91–1.94] |
| S3 | swift | 32 | 12398 | 6.9 | 1.92 [1.91–1.92] |

## S14 skala vertikal (SC1) — kesimpulan hanya untuk 1 sampai 3 core

**Apple Silicon, Docker VM (OrbStack): hasil relatif, bukan absolut.** Postgres tetap 2 CPU; run ditandai *terbatas DB* bila CPU Postgres ≥ 90% dari alokasinya.

| Skenario | App | CPU | RPS saturasi | Efisiensi RPS(n)/(n×RPS(1)) | Catatan |
|---|---|---|---|---|---|
| S3 | go | 1 | 25644 | 1.00 | – |
| S3 | go | 2 | 28464 | 0.55 | app < 85% batas CPU (pembatas lain: k6/DB/VM; efisiensi bukan sifat aplikasi) |
| S3 | go | 3 | 29924 | 0.39 | app < 85% batas CPU (pembatas lain: k6/DB/VM; efisiensi bukan sifat aplikasi) |
| S3 | swift | 1 | 8046 | 1.00 | – |
| S3 | swift | 2 | 12060 | 0.75 | – |
| S3 | swift | 3 | 16016 | 0.66 | – |
| S8 | go | 1 | 14152 | 1.00 | – |
| S8 | go | 2 | 18848 | 0.67 | app < 85% batas CPU (pembatas lain: k6/DB/VM; efisiensi bukan sifat aplikasi) |
| S8 | go | 3 | 19159 | 0.45 | app < 85% batas CPU (pembatas lain: k6/DB/VM; efisiensi bukan sifat aplikasi) |
| S8 | swift | 1 | 2584 | 1.00 | – |
| S8 | swift | 2 | 4221 | 0.82 | – |
| S8 | swift | 3 | 4981 | 0.64 | – |

## SC2 skala konkurensi (turunan tahap A)

| Skenario | App | Kemiringan mem anon maks per 100 VU (MB) | Pertumbuhan thread per VU | Titik lutut latensi (VU; p99 ≥ 2× p99 VU terendah) |
|---|---|---|---|---|
| S3 | go | 4.86 | 0.000 | 128 |
| S3 | swift | 2.57 | 0.000 | 128 |
| S8 | go | 4.92 | 0.000 | 128 |
| S8 | swift | 3.41 | 0.000 | 128 |

## M1 / SC3 skala basis kode: satu modul (T1) vs banyak modul (T2) — macOS native

Run: `20261013-055427`. **Kode sintetis (~101 baris/modul): kurva menunjukkan biaya struktur, bukan kualitas arsitektur.** Konfigurasi dev, cache terisolasi, satu mesin (laptop).

| Stack | Build | Topologi | N=1 (s) | N=3 (s) |
|---|---|---|---|---|
| go | B3 | T1 | 4.74 | 4.18 |
| go | B3 | T2 | 4.29 | 4.03 |
| go | B2-leaf | T1 | 0.30 | 0.28 |
| go | B2-leaf | T2 | 0.28 | 0.28 |
| go | B2-core | T1 | 0.30 | 0.29 |
| go | B2-core | T2 | 0.29 | 0.30 |
| swift | B3 | T1 | 55.65 | 61.45 |
| swift | B3 | T2 | 56.19 | 57.05 |
| swift | B2-leaf | T1 | 4.63 | 4.71 |
| swift | B2-leaf | T2 | 4.73 | 5.02 |
| swift | B2-core | T1 | 5.14 | 5.83 |
| swift | B2-core | T2 | 5.13 | 6.28 |

**Kemiringan waktu build (detik per modul tambahan, regresi linear atas N yang diuji)**

| Stack | Build | Topologi | Kemiringan s/modul |
|---|---|---|---|
| go | B3 | T1 | -0.280 |
| go | B3 | T2 | -0.130 |
| go | B2-leaf | T1 | -0.010 |
| go | B2-leaf | T2 | 0.000 |
| go | B2-core | T1 | -0.005 |
| go | B2-core | T2 | 0.005 |
| swift | B3 | T1 | 2.900 |
| swift | B3 | T2 | 0.430 |
| swift | B2-leaf | T1 | 0.040 |
| swift | B2-leaf | T2 | 0.145 |
| swift | B2-core | T1 | 0.345 |
| swift | B2-core | T2 | 0.575 |

## Developer Experience (DX1–DX5) — macOS native

Run: `dx_20261013-072550.json`. DX terukur bukan keseluruhan DX; faktor tidak terukur ada di bagian Kesimpulan > Tidak diukur.
Asumsi: cold = cache build kosong, dependency sudah diunduh (agar jaringan tidak ikut terukur); warm = tanpa perubahan. Postgres idle berjalan; Go membuka koneksi DB saat start, Swift membuka koneksi lazy (perbedaan perilaku default stack).

**DX1 edit → siap** (build B2 dev + start proses native sampai /healthz 200)

| Stack | Edit→siap s | Build s | Start s |
|---|---|---|---|
| go | 0.66 | 0.58 | 0.06 |
| swift | 6.15 | 5.41 | 0.03 |

**DX2 waktu test suite paritas** (go test ./... vs swift test [Swift Testing])

| Stack | Kasus | Cache build kosong (s) | Cache hangat (s) |
|---|---|---|---|
| go | 52 | 10.64 | 0.39 |
| swift | 52 | 70.61 | 4.60 |

Jumlah kasus sama di kedua suite: Go=52, Swift=52, daftar bersama=52, himpunan ID identik: **True**.

**DX3 ukuran kode dan dependency**

| Stack | Baris kode (prod) | File (prod) | Baris test | File test | Dependency langsung | Dependency transitif | Ukuran cache dependency (MB) |
|---|---|---|---|---|---|---|---|
| go | 807 | 8 | 233 | 1 | 6 | 28 (graf modul) / 15 (terhubung ke binary) | 60.8 |
| swift | 634 | 6 | 152 | 1 | 3 | 35 | 701.8 |

**DX4 diagnostik compiler** (kualitatif; keluaran apa adanya di `results/raw/dx/diagnostics/`; tanpa skor dan tanpa pemenang)

| Stack | Mutasi | Baris keluaran | Menunjuk baris yang benar | Pesan error pertama |
|---|---|---|---|---|
| go | type_mismatch | 2 | ya | `httpapi/httpapi.go:90:15: cannot use "ok" (untyped string constant) as int value in argument to writeJSON` |
| go | undefined_symbol | 2 | ya | `httpapi/httpapi.go:90:37: undefined: domain.NoSuchHelper` |
| go | unhandled_error | 2 | ya | `httpapi/httpapi.go:90:5: declared and not used: err` |
| swift | type_mismatch | 21 | ya | `swift-app/Sources/HTTPAPI/HTTPAPI.swift:66:45: error: cannot convert value of type 'Int' to expected argument type 'String'` |
| swift | undefined_symbol | 20 | ya | `swift-app/Sources/HTTPAPI/HTTPAPI.swift:66:26: error: cannot find 'noSuchHelper' in scope` |
| swift | unhandled_error | 21 | ya | `swift-app/Sources/HTTPAPI/HTTPAPI.swift:66:9: error: call can throw, but it is not marked with 'try' and the error is not handled` |

**DX5 onboarding** (clone bersih → request pertama sukses)

| Stack | Jumlah perintah | Perintah | Prasyarat | Daftar prasyarat | B1 dev s | Start s |
|---|---|---|---|---|---|---|
| go | 5 | make doctor; make db-up; make db-seed; make go-run; GET /users/1 | 4 | docker, make, git, go | 11.1 | 0.06 |
| swift | 5 | make doctor; make db-up; make db-seed; make swift-run; GET /users/1 | 4 | docker, make, git, swift (Xcode 27 / toolchain 6.4) | 82.8 | 0.03 |

## Profil — 10 fungsi teratas (**penjelasan, bukan perbandingan**; macOS native)

### go s8 (15s @ 2000 RPS; RATE dari environment)

Sumber: go tool pprof -top (flat) pada cpu.pb.gz. Berkas mentah: `results/profiles/go/s8`. Laporan tidak menyimpulkan penyebab selisih; narasi hanya bila didukung langsung oleh data profil di bawah.

| # | flat | flat% | cum | cum% | fungsi |
|---|---|---|---|---|---|
| 1 | 2.28s | 48.82 | 2.28s | 48.82 | `syscall.rawsyscalln` |
| 2 | 1.06s | 22.7 | 1.06s | 22.7 | `runtime.kevent` |
| 3 | 0.38s | 8.14 | 0.38s | 8.14 | `runtime.pthread_cond_signal` |
| 4 | 0.34s | 7.28 | 0.34s | 7.28 | `runtime.pthread_cond_wait` |
| 5 | 0.06s | 1.28 | 0.06s | 1.28 | `runtime.usleep` |
| 6 | 0.04s | 0.86 | 0.04s | 0.86 | `runtime.madvise` |
| 7 | 0.03s | 0.64 | 0.04s | 0.86 | `runtime.scanObjectsSmall` |
| 8 | 0.02s | 0.43 | 0.04s | 0.86 | `reflect.Value.Set` |
| 9 | 0.01s | 0.21 | 0.06s | 1.28 | `encoding/json/v2.makeStructArshaler.func2` |
| 10 | 0.01s | 0.21 | 0.72s | 15.42 | `internal/poll.(*FD).Read` |

_Graphviz (dot) tidak terpasang: SVG berupa flame graph buatan tools/lib/flame.py dari pprof -traces, bukan 'pprof -svg'_

### swift s8 (15s @ 2000 RPS; RATE dari environment)

Sumber: macOS sample: 'Sort by top of stack' (semua thread, termasuk thread idle). Berkas mentah: `results/profiles/swift/s8`. Laporan tidak menyimpulkan penyebab selisih; narasi hanya bila didukung langsung oleh data profil di bawah.

**Daftar mentah** (semua thread, termasuk thread idle):

| # | sampel (top of stack) | fungsi | image |
|---|---|---|---|
| 1 | 44670 | `__psynch_cvwait` | libsystem_kernel.dylib |
| 2 | 35113 | `__workq_kernreturn` | libsystem_kernel.dylib |
| 3 | 4467 | `mach_msg2_trap` | libsystem_kernel.dylib |
| 4 | 860 | `start_wqthread` | libsystem_pthread.dylib |
| 5 | 778 | `__psynch_mutexwait` | libsystem_kernel.dylib |
| 6 | 470 | `swift::MetadataCacheKey::operator==(swift::MetadataCacheKey const&) const` | libswiftCore.dylib |
| 7 | 441 | `swift_conformsToProtocolMaybeInstantiateSuperclasses(swift::TargetMetadata<swift::InProcess> const*, swift::Ta` | libswiftCore.dylib |
| 8 | 426 | `_xzm_free_tc` | libsystem_malloc.dylib |
| 9 | 410 | `swift_release` | libswiftCore.dylib |
| 10 | 382 | `swift::StableAddressConcurrentReadableHashMap<swift::GenericCacheEntry, swift::TaggedMetadataAllocator<(unsign` | libswiftCore.dylib |

**Tanpa primitif tunggu thread idle** (disaring: `__psynch_cvwait`, `__psynch_mutexwait`, `__select`, `__semwait_signal`, `__ulock_wait`, `__ulock_wait2`, `__workq_kernreturn`, `_pthread_start`, `_pthread_wqthread`, `kevent`, `mach_msg2_trap`, `mach_msg_trap`, `start_wqthread`, `thread_start`):

| # | sampel (top of stack) | fungsi | image |
|---|---|---|---|
| 1 | 470 | `swift::MetadataCacheKey::operator==(swift::MetadataCacheKey const&) const` | libswiftCore.dylib |
| 2 | 441 | `swift_conformsToProtocolMaybeInstantiateSuperclasses(swift::TargetMetadata<swift::InProcess> const*, swift::Ta` | libswiftCore.dylib |
| 3 | 426 | `_xzm_free_tc` | libsystem_malloc.dylib |
| 4 | 410 | `swift_release` | libswiftCore.dylib |
| 5 | 382 | `swift::StableAddressConcurrentReadableHashMap<swift::GenericCacheEntry, swift::TaggedMetadataAllocator<(unsign` | libswiftCore.dylib |
| 6 | 357 | `getCache(swift::TargetTypeContextDescriptor<swift::InProcess> const&)` | libswiftCore.dylib |
| 7 | 356 | `swift::TargetContextDescriptor<swift::InProcess>::getGenericContext() const` | libswiftCore.dylib |
| 8 | 312 | `_platform_memmove` | libsystem_platform.dylib |
| 9 | 299 | `_xzm_malloc_tc` | libsystem_malloc.dylib |
| 10 | 261 | `swift_retain` | libswiftCore.dylib |

Trace Instruments (Time Profiler) tersimpan: `results/profiles/swift/s8/timeprofiler.trace`.

## Kesimpulan DX dan skalabilitas

Aturan: satu stack dinyatakan lebih baik hanya bila rentang min–maks kedua stack tidak tumpang tindih dan selisih median > 5%; selain itu 'setara' atau 'belum cukup bukti' (ulangan < 2). Setiap kalimat menunjuk tabel/metrik sumbernya. DX4 tidak diberi skor.

### Ringkasan

**DX.** DX3 baris kode produksi (deskriptif) (deterministik): Go 807, Swift 634, rasio Swift/Go 0.79× [0.79–0.79] → **Swift lebih sedikit (rentang tidak tumpang tindih, selisih median 21%)** [tabel DX3]; DX3 dependency transitif (deskriptif) (Go: graf modul; Swift: Package.resolved): Go 28, Swift 35, rasio Swift/Go 1.25× [1.25–1.25] → **Go lebih sedikit (rentang tidak tumpang tindih, selisih median 25%)** [tabel DX3]; Ukuran image (distroless; deskriptif) (MB, deterministik): Go 16.9, Swift 122.8, rasio Swift/Go 7.27× [7.27–7.27] → **Go lebih kecil (rentang tidak tumpang tindih, selisih median 627%)** [tabel S12]

**Skalabilitas.** Belum ada temuan skalabilitas yang lolos aturan (lihat matriks).

_Catatan: data beban saat ini hanya smoke (1 ulangan); kesimpulan beban belum dapat ditarik._

### Matriks kriteria

| Metrik | Kondisi | Go (median [rentang]) | Swift (median [rentang]) | Rasio Swift/Go [rentang] | Hasil |
|---|---|---|---|---|---|
| Build B1 dev | wall s, macOS native | 11.42 | 87.41 | 7.65× [7.65–7.65] | belum cukup bukti (ulangan < 2) |
| Build B1 release | wall s, macOS native | 11.04 | 141.59 | 12.83× [12.83–12.83] | belum cukup bukti (ulangan < 2) |
| Build B2 dev | wall s, macOS native | 0.59 | 5.63 | 9.54× [9.54–9.54] | belum cukup bukti (ulangan < 2) |
| Build B2 release | wall s, macOS native | 0.44 | 8.74 | 19.86× [19.86–19.86] | belum cukup bukti (ulangan < 2) |
| Build B3 dev | wall s, macOS native | 9.67 | 63.30 | 6.55× [6.55–6.55] | belum cukup bukti (ulangan < 2) |
| Build B3 release | wall s, macOS native | 9.10 | 115.52 | 12.69× [12.69–12.69] | belum cukup bukti (ulangan < 2) |
| DX1 edit→siap | detik, macOS native | 0.66 | 6.15 | 9.37× [9.37–9.37] | belum cukup bukti (ulangan < 2) |
| DX2 test suite (cache build kosong) | detik | 10.64 | 70.61 | 6.64× [6.64–6.64] | belum cukup bukti (ulangan < 2) |
| DX2 test suite (cache hangat) | detik | 0.39 | 4.60 | 11.79× [11.79–11.79] | belum cukup bukti (ulangan < 2) |
| DX3 baris kode produksi (deskriptif) | deterministik | 807 | 634 | 0.79× [0.79–0.79] | Swift lebih sedikit (rentang tidak tumpang tindih, selisih median 21%) |
| DX3 dependency transitif (deskriptif) | Go: graf modul; Swift: Package.resolved | 28 | 35 | 1.25× [1.25–1.25] | Go lebih sedikit (rentang tidak tumpang tindih, selisih median 25%) |
| DX5 onboarding (B1 dev) | detik | 11.1 | 82.8 | 7.45× [7.45–7.45] | belum cukup bukti (ulangan < 2) |
| Waktu start (distroless) | ms; termasuk overhead Docker yang sama | 226 [223–228] | 249 [206–293] ⚠CV25% | 1.10× [0.90–1.31] | setara (rentang tumpang tindih atau selisih median ≤ 5%) |
| Ukuran image (distroless; deskriptif) | MB, deterministik | 16.9 | 122.8 | 7.27× [7.27–7.27] | Go lebih kecil (rentang tidak tumpang tindih, selisih median 627%) |
| Efisiensi skala S14 S3 pada 2 core | RPS(n)/(n×RPS(1)); hanya 1–3 core | 0.55 | 0.75 | 1.35× [1.35–1.35] | belum cukup bukti (ulangan < 2) |
| Efisiensi skala S14 S3 pada 3 core | RPS(n)/(n×RPS(1)); hanya 1–3 core | 0.39 | 0.66 | 1.71× [1.71–1.71] | belum cukup bukti (ulangan < 2) |
| Efisiensi skala S14 S8 pada 2 core | RPS(n)/(n×RPS(1)); hanya 1–3 core | 0.67 | 0.82 | 1.23× [1.23–1.23] | belum cukup bukti (ulangan < 2) |
| Efisiensi skala S14 S8 pada 3 core | RPS(n)/(n×RPS(1)); hanya 1–3 core | 0.45 | 0.64 | 1.42× [1.42–1.42] | belum cukup bukti (ulangan < 2) |
| Kemiringan memori anon maks per 100 VU S3 | MB per 100 VU | 4.86 | 2.57 | 0.53× [0.53–0.53] | belum cukup bukti (ulangan < 2) |
| Kemiringan memori anon maks per 100 VU S8 | MB per 100 VU | 4.92 | 3.41 | 0.69× [0.69–0.69] | belum cukup bukti (ulangan < 2) |
| Kemiringan build B2-leaf topologi T1 | s per modul; kode sintetis | -0.010 | 0.040 | – | belum cukup bukti (ulangan < 2) |
| Kemiringan build B2-leaf topologi T2 | s per modul; kode sintetis | 0.000 | 0.145 | – | belum cukup bukti (ulangan < 2) |
| Kemiringan build B3 topologi T1 | s per modul; kode sintetis | -0.280 | 2.900 | – | belum cukup bukti (ulangan < 2) |
| Kemiringan build B3 topologi T2 | s per modul; kode sintetis | -0.130 | 0.430 | – | belum cukup bukti (ulangan < 2) |

### Rekomendasi arsitektur kondisional (monorepo satu modul vs banyak modul)

Belum ada rekomendasi yang didukung data (rentang tumpang tindih, selisih ≤ 5%, atau ulangan < 2 pada rentang N yang diuji).

### Tidak diukur (tanpa bobot; tidak dicampur dengan temuan terukur)

- **Kematangan ekosistem dan library** — dari pengetahuan umum: ekosistem Go untuk layanan web/ORM jauh lebih luas; Vapor/Fluent lebih kecil. Tidak diukur di sini.
- **Dukungan IDE dan debugging** — dari pengetahuan umum; tidak diukur.
- **Ketersediaan engineer** — dari pengetahuan umum; tidak diukur.
- **Stabilitas rilis** — transisi Vapor 4 ke 5 (Vapor 5 Beta 1, 15 September 2026; WebSocket dan kompresi belum ada; tidak disarankan produksi) bersumber dari [Vapor blog](https://blog.vapor.codes/posts/vapor-5-beta/) sebagaimana dikutip di `docs/PRD.md`; tidak diukur.

### Batas kesimpulan

- Hasil berlaku untuk MacBook Pro M2 Pro (satu mesin, laptop), versi yang dikunci, VM Docker OrbStack (beban) dan macOS native (build/DX/modular/profil).
- Skala vertikal hanya untuk 1–3 core; M1 memakai kode sintetis dan hanya rentang N yang diuji (default 1, 5, 20); S14 bisa terbatas DB (ditandai).
- Penyebab selisih tidak disimpulkan tanpa dukungan profil (bagian Profil) atau dokumentasi yang dikutip.

## Grafik

- `results/charts/rps_vs_vu_s1.png`
- `results/charts/latency_vs_rate_s1.png`
- `results/charts/rps_vs_vu_s2.png`
- `results/charts/latency_vs_rate_s2.png`
- `results/charts/rps_vs_vu_s3.png`
- `results/charts/latency_vs_rate_s3.png`
- `results/charts/rps_vs_vu_s4.png`
- `results/charts/latency_vs_rate_s4.png`
- `results/charts/rps_vs_vu_s5.png`
- `results/charts/latency_vs_rate_s5.png`
- `results/charts/rps_vs_vu_s6.png`
- `results/charts/latency_vs_rate_s6.png`
- `results/charts/rps_vs_vu_s7.png`
- `results/charts/latency_vs_rate_s7.png`
- `results/charts/rps_vs_vu_s8.png`
- `results/charts/latency_vs_rate_s8.png`
- `results/charts/rps_vs_vu_s9.png`
- `results/charts/latency_vs_rate_s9.png`
- `results/charts/cpu_vs_time_s8.png`
- `results/charts/mem_vs_time_s8.png`
- `results/charts/build_time.png`

