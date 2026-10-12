# ADR: Benchmark Backend Go vs Swift

Oct 13, 2026 · @Aris Ripandi

Empat belas keputusan di bawah mengunci stack, topologi uji pada MacBook M2 Pro, logging, seed data, pengukuran resource, build time, startup, varian tuned, profiling, base image, Developer Experience, dan skalabilitas. Semuanya berstatus Diterima per 13 Oktober 2026 dan menjadi dasar PRD versi 4.

## Ringkasan keputusan

| ID | Keputusan | Status |
| --- | --- | --- |
| ADR-001 | Stack Swift utama adalah Vapor 4 + Fluent 4. Vapor 5 beta hanya varian eksperimental. | Diterima |
| ADR-002 | Semua komponen benchmark beban berjalan sebagai container linux/arm64 di Docker Desktop pada Mac. Profil `mac-m2`, hasil dibaca sebagai perbandingan relatif. | Diterima, diperbarui |
| ADR-003 | k6 (seri v2) sebagai load generator, dijalankan dalam container di jaringan yang sama dengan aplikasi. | Diterima |
| ADR-004 | Go memakai LogLayer + transport `log/slog`. Vapor memakai SwiftLog bawaan. Dua mode log: `quiet` dan `access`. | Diterima |
| ADR-005 | Seed data deterministik dari satu file SQL yang sama, ditambah fixture kecil dengan respons acuan untuk uji kontrak. | Diterima |
| ADR-006 | Metrik resource dikumpulkan oleh container sampler, bukan stack monitoring penuh. | Diterima |
| ADR-007 | Makefile menjadi satu-satunya pintu masuk untuk build, run, dan benchmark. | Diterima, diperbarui |
| ADR-008 | Build time diukur native di macOS: B1 bersih, B2 inkremental, B3 dependency ter-cache, dengan cache terisolasi. | Diterima |
| ADR-009 | Ukuran image, waktu start, latensi request pertama, dan memori idle diukur sebagai skenario S12. | Diterima, diperbarui |
| ADR-010 | Varian `tuned` per stack dilaporkan terpisah dari default (skenario S13). | Diterima |
| ADR-011 | Profiling di run terpisah dengan aplikasi native, hanya untuk menjelaskan selisih. | Diterima |
| ADR-012 | Image runtime memakai Distroless (default) atau Alpine lewat `IMAGE_FLAVOR`, dibuktikan dengan menjalankan binary. | Diterima |
| ADR-013 | DX dinilai dari DX1 sampai DX5, dan kesimpulan hanya bila selisih melampaui variasi antar ulangan. | Diterima |
| ADR-014 | Monorepo modular dengan lapisan setara. Skalabilitas dinilai lewat SC1 (S14), SC2, dan SC3 (eksperimen M1, satu modul vs banyak modul). | Diterima |

## ADR-001: Vapor 4 + Fluent 4 sebagai stack Swift utama

**Status:** Diterima. **Keputusan:** stack Swift utama memakai Vapor 4 (rilis 4.x terbaru) dengan Fluent 4 di Swift 6.4.0, dan Vapor 5 beta hanya menjadi varian eksperimental.

**Konteks.** Permintaan awal hanya menyebut "Vapor dan Fluent". Per 13 Oktober 2026, Vapor 4 masih versi stabil resmi, sedangkan Vapor 5 baru Beta 1 (15 September 2026). Beta itu wajib Swift 6.4, belum punya WebSocket dan kompresi, belum disarankan untuk produksi, dan integrasi Fluent-nya masih lewat FluentKit langsung di template ([Vapor blog](https://blog.vapor.codes/posts/vapor-5-beta/)).

**Konsekuensi.**

- Hasil utama mewakili stack yang benar-benar dipakai di produksi hari ini.
- Varian `swift-app-v5` boleh ditambahkan setelah stack utama lulus semua kriteria, dengan label "eksperimental" di laporan.
- Bila Vapor 5 rilis stabil, benchmark bisa diulang dengan mengganti satu direktori aplikasi.

**Alternatif yang ditolak.** Vapor 5 beta sebagai stack utama: angka bisa berubah antar beta, dan integrasi ORM belum final.

## ADR-002: Topologi uji di Docker Desktop pada MacBook M2 Pro

**Status:** Diterima (menggantikan asumsi "host Linux" di PRD versi 1). **Keputusan:** semua komponen (Postgres, aplikasi, k6, sampler) berjalan sebagai container linux/arm64 di Docker Desktop, memakai profil resource `mac-m2`, dan hasilnya dibaca sebagai perbandingan relatif Go vs Swift, bukan angka absolut server.

**Konteks.** Host pengguna adalah MacBook Pro M2 Pro dengan RAM 16 GB. Docker di Mac menjalankan container di dalam VM Linux, jadi cgroup dan jaringan yang diukur adalah milik VM. Core fisik M2 Pro terbagi jadi performance dan efficiency, dan macOS yang menjadwalkannya, sehingga pinning ke core fisik tidak mungkin dari dalam VM. Image resmi Go dan Swift tersedia untuk arm64, jadi emulasi amd64 tidak perlu dan harus dihindari.

**Profil `mac-m2`.**

| Komponen | CPU | Memori | Catatan |
| --- | --- | --- | --- |
| VM Docker Desktop (diatur manual di Settings, Resources) | 8 vCPU | 8 GB | Menyisakan sedikitnya 2 core dan 8 GB untuk macOS |
| Aplikasi (Go atau Swift, satu aktif) | 2 | 1 GB | Batas sama persis untuk keduanya |
| Postgres | 2 | 2 GB | `shared_buffers` 512 MB, data di named volume (bukan bind mount) |
| k6 | 2 | 1 GB | Di jaringan Docker yang sama, tanpa melewati port publish |
| sampler | kecil | 128 MB | Hanya membaca statistik |

**Aturan operasional di Mac.** Charger tersambung, Low Power Mode mati, aplikasi berat lain ditutup, dan run dibungkus `caffeinate` agar Mac tidak tidur. Orkestrator mencatat status thermal (`pmset -g therm`) sebelum dan sesudah run, dan menandai run yang terkena throttling.

**Konsekuensi.**

- Angka RPS lebih rendah dan lebih bising dibanding server Linux. Rasio Swift terhadap Go dan bentuk kurvanya tetap bermakna, nilai absolutnya tidak.
- Durasi run dipangkas (lihat PRD) karena laptop, dan jumlah ulangan default turun dari 5 menjadi 3. Keduanya bisa dinaikkan lewat variabel Makefile.
- Setiap laporan memuat label "Apple Silicon, Docker Desktop VM" dan tidak boleh dibandingkan langsung dengan hasil dari mesin lain.

**Alternatif yang ditolak.** Menjalankan k6 di macOS dan menembak port yang dipublikasikan Docker: menambah proxy jaringan Docker Desktop ke jalur ukur. Menjalankan aplikasi native di macOS: tidak setara untuk Postgres, cgroup, dan batas resource.

**Pembaruan 13 Oktober 2026.** Pengukuran build time (ADR-008) dan profiling (ADR-011) berjalan native di macOS, bukan di VM Docker. Keduanya tidak boleh berjalan bersamaan dengan beban Docker, dan membutuhkan Go 1.27.2 serta toolchain Swift 6.4 terpasang di Mac. Benchmark beban tetap sepenuhnya di container.

## ADR-003: k6 sebagai load generator dalam container

**Status:** Diterima. **Keputusan:** load test memakai Grafana k6 seri v2 (image `grafana/k6`, versi persis dikunci saat setup), dijalankan dalam container di jaringan Docker yang sama dengan aplikasi.

**Konteks.** Pengguna meminta k6. Menurut [catatan migrasi k6 v2](https://qaskills.sh/blog/k6-2-migration-guide-breaking-changes), v2.0.0 rilis 11 Mei 2026 dan v2.3.0 tercatat sebagai rilis terbaru per 28 September 2026. Dokumentasi resmi k6 menandai v2.0.x sebagai versi terbaru dan menyediakan executor `constant-vus`, `ramping-vus`, dan [`constant-arrival-rate`](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate.md). Executor `constant-arrival-rate` bersifat open-model: iterasi dimulai terlepas dari respons sistem, sehingga cocok untuk mengukur latensi pada laju tetap tanpa coordinated omission.

**Konsekuensi.**

- Tahap A (tangga konkurensi) memakai `ramping-vus` atau `constant-vus`, tahap B (laju tetap) memakai `constant-arrival-rate` dengan `preAllocatedVUs` dan `maxVUs` yang cukup.
- k6 memakai JavaScript dan lebih boros CPU dibanding alat seperti wrk. Pada profil `mac-m2` k6 mendapat 2 vCPU, dan run dibuang bila CPU k6 melewati 80%.
- Karena k6 v2 mengubah beberapa perintah dan executor lama, skrip hanya memakai executor yang masih dipelihara.
- Setiap titik ukur adalah satu invokasi k6 dengan ringkasan JSON (\`--summary-export\`) yang disimpan untuk agregasi. Keluaran per request tidak disimpan karena terlalu besar pada ribuan RPS.

**Alternatif yang ditolak.** wrk atau wrk2 (lebih ringan, tetapi skenario campuran dan body dinamis memerlukan Lua). oha dan vegeta tetap boleh dipakai sebagai validasi silang untuk skenario tanpa database (S1), bukan sebagai alat utama.

## ADR-004: Strategi logging

**Status:** Diterima (menggantikan aturan "log mati" di PRD versi 1). **Keputusan:** Go memakai [LogLayer for Go](https://go.loglayer.dev/) dengan transport [`log/slog`](https://go.loglayer.dev/transports/slog.html), Vapor memakai logging bawaan berbasis [SwiftLog](https://docs.vapor.codes/basics/logging/), dan keduanya punya dua mode: `quiet` (default benchmark) dan `access`.

**Konteks.** Logging ikut menentukan biaya per request, jadi harus ada di kedua aplikasi dan diukur, bukan dimatikan. LogLayer v3 menyediakan modul `go.loglayer.dev/v3`, transport slog `go.loglayer.dev/transports/slog/v3`, dan middleware HTTP `go.loglayer.dev/integrations/loghttp/v3` yang kompatibel dengan chi. Middleware itu menurunkan logger per request dengan `requestId`, `method`, `path`, lalu menulis satu baris "request completed" berisi status, durasi, dan byte. Vapor memakai SwiftLog: logger per request tersedia lewat `req.logger` dengan metadata `request-id`, level diatur lewat `LOG_LEVEL` atau flag `--log`, dan `RouteLoggingMiddleware` tersedia untuk log akses.

**Desain.**

| Aspek | Go | Swift |
| --- | --- | --- |
| Pustaka | `go.loglayer.dev/v3` dengan transport slog, handler `slog.NewTextHandler` ke stdout | SwiftLog lewat `LoggingSystem.bootstrap(from: &env)` bawaan Vapor |
| Log per request | `loghttp.Middleware` dipasang di chi, handler memakai `loghttp.FromRequest(r)` | `req.logger` bawaan, `RouteLoggingMiddleware(logLevel: .info)` hanya di mode `access` |
| Mode `quiet` | Level `error`. Logger per request dan request ID tetap dibuat, baris "request completed" tersaring | `LOG_LEVEL=error`. `request-id` per request tetap dibuat oleh Vapor |
| Mode `access` | Level `info`, satu baris akses per request | `LOG_LEVEL=info` dan `RouteLoggingMiddleware` aktif |
| Pengaturan | Variabel `LOG_MODE` dan `LOG_FORMAT` (`text` default, `json` varian) | Variabel `LOG_MODE` yang diterjemahkan ke `LOG_LEVEL` dan middleware |
| Tujuan keluaran | stdout, driver log Docker `local` dengan rotasi | stdout, driver log Docker `local` dengan rotasi |

**Konsekuensi.**

- Mode `quiet` adalah default semua skenario, karena baseline kedua stack sama-sama membuat logger dan request ID per request.
- Skenario P1 S11 menjalankan S8 pada laju tetap dengan mode `quiet` lalu `access`, sehingga selisih CPU, memori, dan latensi menunjukkan biaya logging per stack.
- Biaya LogLayer (API fluent dan pipeline plugin) di atas slog ikut terukur. Itu disengaja karena pengguna meminta LogLayer, dan dicatat di laporan sebagai bagian dari stack Go.
- Handler bawaan Vapor mencetak teks, bukan JSON. Agar format sebanding, Go memakai handler teks slog secara default. Varian JSON Go hanya dilaporkan sebagai tambahan.
- Metadata logger Vapor hanya tampil pada level debug atau lebih rendah menurut dokumentasi, jadi pada mode `access` baris log Vapor lebih ringkas daripada baris loghttp. Perbedaan ini dinyatakan di laporan.

**Alternatif yang ditolak.** Hanya `log/slog` tanpa LogLayer (tidak sesuai permintaan). Mematikan log total (menyembunyikan biaya yang nyata di produksi). Handler JSON pihak ketiga di Vapor (tidak lagi "bawaan").

## ADR-005: Seed data deterministik dan bersama

**Status:** Diterima. **Keputusan:** skema dan data dibuat oleh satu set file SQL di `db/` yang dipakai kedua aplikasi apa adanya. Aplikasi tidak boleh membuat tabel atau mengisi data sendiri, dan tidak ada auto-migrate di GORM maupun Fluent.

**Konteks.** Perbandingan hanya adil bila kedua stack membaca baris yang sama dengan distribusi yang sama. Seed yang dibuat lewat kode masing-masing bahasa akan menghasilkan data berbeda, dan seed acak tanpa kunci membuat hasil antar run tidak sebanding.

**Dua lapis data.**

| Lapis | Isi | Dipakai untuk |
| --- | --- | --- |
| Fixture kecil (`db/fixtures/`) | 20 user dan 100 order dengan nilai tetap tulisan tangan, termasuk kasus tepi: user tanpa order, order berstatus tiap jenis, `note` kosong dan `note` 200 karakter | Uji kontrak. Respons acuan (golden JSON) disimpan di repo dan harus cocok persis dengan kedua aplikasi |
| Seed benchmark (`db/seed.sql`) | 10.000 user dan 500.000 order, dibuat dengan `generate_series` dan fungsi hash deterministik (tanpa `random()` tak ber-seed) | Semua skenario beban |

**Distribusi seed benchmark.**

- `user_id` pada order condong ringan: `1 + floor(10000 * u^1.2)` dengan `u` dari hash deterministik, sehingga user berorder paling banyak punya sekitar 250 order dan rata-rata tetap 50.
- Status: 20% `pending`, 50% `paid`, 20% `shipped`, 10% `cancelled`. Ada sekitar 100.000 order `pending` untuk skenario `pay`.
- `created_at` tersebar selama 365 hari terakhir dari tanggal tetap, `total_cents` antara 500 dan 500.000, dan `note` berupa teks pendek deterministik.
- Seed mengekspor daftar ID (`loadtest/data/*.json`): ID user, ID order, dan ID order `pending`, sehingga k6 memilih ID yang pasti ada.

**Bukti kesamaan data.** Setelah seed, skrip mencetak checksum per tabel (hash dari seluruh baris terurut). Checksum dan hasil `VACUUM ANALYZE` dicatat di setiap laporan, dan reset antar run memakai `CREATE DATABASE ... TEMPLATE` dari database yang sudah di-seed.

**Konsekuensi.**

- Skema bersumber SQL, jadi model GORM dan Fluent memetakan tabel yang ada dengan nama eksplisit.
- Ukuran seed muat di memori Postgres (2 GB), sehingga benchmark mengukur overhead aplikasi, ORM, dan protokol, bukan disk.
- Mengubah distribusi seed berarti mengubah checksum, dan laporan lama tidak boleh dibandingkan dengan laporan baru.

**Alternatif yang ditolak.** Seeder di tiap bahasa (data berbeda), dump biner Postgres (tidak terbaca dan tidak bisa ditinjau di repo), dan seed acak per run (tidak bisa diulang).

## ADR-006: Pengumpulan metrik resource lewat sampler sidecar

**Status:** Diterima (menggantikan sampler di host pada PRD versi 1). **Keputusan:** satu container `sampler` ringan membaca statistik cgroup v2 dan `/proc` tiap 1 detik untuk container yang sedang diuji, lalu menulis CSV per run. `docker stats` dicatat sebagai pembanding silang. Stack monitoring penuh (cAdvisor, Prometheus, Grafana) hanya profil opsional.

**Konteks.** Di Mac, cgroup dan proses container berada di dalam VM Docker Desktop, jadi skrip di macOS tidak bisa membaca `/sys/fs/cgroup`. Sampler harus berjalan di sisi VM.

**Desain.**

- Container sampler memakai `pid: host` dan `cgroup: host` (opsi Compose) dengan akses baca saja, sehingga melihat cgroup dan proses VM. Jalur cgroup container target ditemukan dari ID container, dan agen wajib memverifikasi jalurnya saat `make doctor` karena bergantung pada driver cgroup Docker Desktop.
- Metrik: `cpu.stat` (usage, user, system, throttled), `memory.current`, `memory.peak`, `memory.stat`, `pids.current`, serta `/proc/<pid>` untuk thread, file descriptor, context switch, dan I/O jaringan.
- Bila sidecar tidak bisa membaca cgroup di lingkungan tertentu, sampler turun ke `docker stats --no-stream` tiap 1 detik dengan fidelitas lebih rendah (tanpa pemisahan user vs system), dan laporan menandai hal itu.
- Go juga mengekspos `runtime/metrics` di port admin 6060 untuk goroutine, siklus GC, dan jeda GC.

**Konsekuensi.**

- Overhead pengukuran kecil: baca file tiap detik, di container dengan batas CPU sendiri.
- Data resource mewakili cgroup di VM, bukan core fisik Mac. Itu cukup untuk membandingkan dua stack di lingkungan yang sama.
- Stack monitoring penuh mati secara default agar tidak berebut CPU dengan aplikasi dan k6 di laptop.

**Alternatif yang ditolak.** Sampler di macOS lewat `docker exec` per detik (overhead dan jitter lebih tinggi, dan image distroless tidak punya shell). Hanya mengandalkan `docker stats` (tidak ada pemisahan user vs system dan tidak ada throttling).

## ADR-007: Makefile sebagai satu pintu masuk

**Status:** Diterima. **Keputusan:** semua operasi (cek prasyarat, database, build, run, uji kontrak, benchmark, laporan, bersih-bersih) dijalankan lewat target Makefile di root repo, dengan `make help` sebagai daftar bantuan.

**Konteks.** Pengguna ingin kemudahan: satu perintah untuk build dan run tiap aplikasi, dan satu perintah untuk benchmark. Aplikasi perlu bisa dijalankan dua cara: native di macOS untuk pengembangan cepat, dan di container untuk benchmark yang sah.

**Target utama.**

| Kelompok | Target | Fungsi |
| --- | --- | --- |
| Bantuan | `help`, `doctor` | Daftar target. `doctor` mengecek arsitektur (arm64), versi Docker, alokasi VM Docker (CPU dan RAM), akses sampler ke cgroup, charger, dan status thermal |
| Database | `db-up`, `db-down`, `db-seed`, `db-reset`, `db-psql` | Jalankan Postgres, seed, reset dari template, buka `psql` |
| Go | `go-build`, `go-run`, `go-test`, `go-image`, `go-up`, `go-down`, `go-logs` | `go-build` dan `go-run` native di Mac. `go-image` dan `go-up` memakai container dengan batas resource profil |
| Swift | `swift-build`, `swift-run`, `swift-test`, `swift-image`, `swift-up`, `swift-down`, `swift-logs` | Sama seperti Go. Jika toolchain Swift 6.4 belum terpasang di Mac, target native memakai container |
| Verifikasi | `contract` | Uji kontrak, jumlah query, dan konfigurasi untuk kedua aplikasi |
| Benchmark | `bench-smoke`, `bench-core`, `bench`, `report` | Smoke cepat, skenario inti, semua skenario, dan pembuat laporan |
| Bersih | `clean`, `clean-all` | Hapus hasil dan artefak, atau hapus juga image dan volume |

**Variabel yang bisa diubah di baris perintah.** `APP=go|swift|both`, `SCENARIO=s1,s3,s8|core|all`, `REPEATS=3`, `LOG_MODE=quiet|access`, `LOG_FORMAT=text|json` (hanya Go), `PROFILE=mac-m2`, `SLO_P99_MS=250`.

**Konsekuensi.**

- Eksekusi native (`go-run`, `swift-run`) hanya untuk pengembangan. Benchmark selalu memakai container dan menolak berjalan dari proses native.
- Satu perintah menjalankan alur penuh: `make bench APP=both SCENARIO=core`.
- Makefile tidak berisi logika rumit. Logika panjang tinggal di skrip `tools/`, sehingga Makefile tetap terbaca.

**Alternatif yang ditolak.** Skrip shell terpisah per tugas (sulit ditemukan), dan `just` atau `task` (menambah dependensi yang belum tentu terpasang, sedangkan `make` sudah tersedia di macOS dengan Xcode Command Line Tools).

**Pembaruan 13 Oktober 2026.** Target baru: `build-bench`, `build-bench-clean`, `build-bench-incr`, `build-bench-cached` (ADR-008), `startup-bench` (ADR-009), `bench-tuned` dan variabel `VARIANT` (ADR-010), serta `profile` (ADR-011). Variabel baru: `BUILD_REPEATS`, `BUILD_CONFIG` (dev, release, atau both), `VARIANT`, dan `DURATION` untuk profiling.

## ADR-008: Benchmark build time native di macOS

**Status:** Diterima. **Keputusan:** build time diukur native di macOS (bukan di Docker) untuk tiga skenario, B1 build bersih tanpa cache, B2 build ulang setelah mengubah satu file, dan B3 build dengan dependency sudah ter-cache, dalam dua konfigurasi (`dev` dan `release`), memakai direktori cache terisolasi.

**Konteks.** Pengguna memilih tiga skenario itu dan lingkungan native macOS untuk mewakili pengalaman developer. Perbedaan kedua toolchain besar: Go memakai build cache dan module cache (`GOCACHE`, `GOMODCACHE`), sedangkan SwiftPM menyediakan opsi `--scratch-path`, `--cache-path`, `--config-path`, `--security-path`, dan `-j` serta cache global default `~/Library/Caches/org.swift.swiftpm/` di macOS ([contoh opsi SwiftPM](https://code.webartifex.biz/alexander/oh-my-zsh/raw/commit/041c35ffc8cd97dd6327f44e35fa777af6f8e845/plugins/swiftpm/_swift), [diskusi cache global](https://forums.swift.org/t/pitch-compilation-caching-support-in-swiftpm/88079)). Swift 6.4 menjadikan Swift Build sistem build default ([InfoWorld](https://www.infoworld.com/article/4225734/apple-touts-simpler-and-clearer-code-with-swift-6-4.html)). Ada pitch compilation caching untuk SwiftPM, jadi agen harus memastikan fitur itu tidak aktif agar B1 dan B3 tidak terbantu cache tersembunyi.

**Definisi skenario.**

| ID | Kondisi awal | Go | Swift |
| --- | --- | --- | --- |
| B1 | Semua cache kosong, termasuk dependency | `GOCACHE` dan `GOMODCACHE` baru dan kosong, lalu `go mod download` dan `go build` | `--scratch-path` dan `--cache-path` baru dan kosong, lalu `swift package resolve` dan `swift build` |
| B2 | Semua cache hangat dan hasil build ada. Satu file diubah (string literal di handler) | `go build` | `swift build` |
| B3 | Sumber dependency sudah ada, artefak kompilasi dibuang | `go clean -cache` (module cache dipertahankan), lalu `go build` | `swift package clean` (checkouts dipertahankan), lalu `swift build` |

B1 dilaporkan sebagai total dan sebagai rincian (unduh dependency vs kompilasi), karena unduhan bergantung jaringan dan kompilasi tidak. Konfigurasi `dev` adalah `go build` biasa dan `swift build` (debug). Konfigurasi `release` memakai flag benchmark (`-trimpath -ldflags='-s -w'` untuk Go, `-c release` untuk Swift). Opsi `--static-swift-stdlib` dipakai pada build Linux di image, dan agen wajib memverifikasi apakah macOS mendukungnya sebelum memakainya di build native.

**Aturan pengukuran.**

- Cache terisolasi dibuat di direktori sementara berakhiran `.noindex` agar cache global pengguna tidak terhapus dan Spotlight tidak ikut mengindeks.
- Paralelisme default toolchain dipakai (mewakili pengalaman developer) dan dicatat bersama jumlah core. Tidak ada tuning `-j`.
- Pengukuran lewat `/usr/bin/time -l`: wall time, CPU user dan system, serta peak RSS, ditambah ukuran binary hasil build.
- Ulangan default: B1 sebanyak 3, B2 sebanyak 5, B3 sebanyak 3 (`BUILD_REPEATS`). Urutan Go dan Swift diselang-seling, ada jeda sampai status thermal normal, dan tidak ada beban Docker yang berjalan bersamaan.
- Setelah B2, hash binary harus berubah sebagai bukti terjadi kompilasi ulang. Build yang gagal membatalkan run.

**Konsekuensi.**

- Go 1.27.2 dan toolchain Swift 6.4 harus terpasang native di Mac (Xcode 27 atau toolchain swift.org). `make doctor` menolak `build-bench` bila tidak ada dan tidak memasang apa pun otomatis.
- Hasil mewakili Mac ini dan pengalaman developer, bukan CI Linux. Waktu build image Docker tidak diukur.
- Laptop dan proses latar macOS menambah noise, sehingga laporan menyertakan median, rentang, dan CV.

**Alternatif yang ditolak.** Mengukur di Docker (lapisan VM dan cache BuildKit mengaburkan pengalaman developer). Menghapus cache global pengguna (merusak lingkungan kerja).

## ADR-009: Ukuran image, startup, dan cold start

**Status:** Diterima. **Keputusan:** skenario P1 S12 mengukur ukuran image dan binary, waktu dari container dibuat sampai `/healthz` sukses pertama, latensi request pertama per endpoint, dan memori idle sesudah start, dengan 10 ulangan per stack.

**Konteks.** Pengguna memilih ukuran image dan startup sebagai tambahan. Kedua stack berbeda jauh di sini: Go menghasilkan satu binary statis, sedangkan Swift membawa runtime dan stdlib yang ukurannya bergantung pada cara link dan image runtime. Request pertama juga mahal dengan cara berbeda: koneksi pool dibuka malas, statement disiapkan pertama kali, dan cache ORM terisi.

**Cara ukur.**

| Metrik | Cara ukur |
| --- | --- |
| Ukuran image dan binary | `docker image inspect` untuk ukuran dan jumlah layer, serta ukuran binary di dalam image |
| Waktu start sampai siap | Dari perintah membuat container (image sudah ada, Postgres sudah hidup) sampai respons 200 pertama dari `/healthz`, dengan polling tiap 10 ms dari container di jaringan yang sama |
| Latensi request pertama | Satu request pertama ke endpoint S1, S3, S4, dan S6 dalam urutan tetap, sebelum warm-up, dicatat per endpoint |
| Memori idle | Memori container 5 detik setelah siap, dan lagi setelah 100 request pertama |

Setiap ulangan me-restart container dari awal dan mereset database dari template bila endpoint menulis data.

**Konsekuensi.**

- Waktu start mencakup overhead pembuatan container Docker yang sama untuk kedua stack. Laporan menyebutkannya dan hanya membandingkan selisih antar stack.
- Cache halaman OS sudah hangat karena image sudah ada, jadi "cold start" di sini berarti proses baru, bukan unduh image.
- Angka ini berguna untuk perkiraan skala dan deploy, bukan pengganti uji beban.

**Alternatif yang ditolak.** Memasukkan waktu unduh image (bergantung jaringan, bukan sifat stack). Mengukur proses native (tidak sama dengan lingkungan container yang dipakai benchmark).

**Pembaruan 13 Oktober 2026.** Ukuran image dan startup kini diukur untuk flavor `distroless` (default) dan `alpine` (opsional), mengikuti ADR-012. Image Distroless tidak punya shell, jadi polling `/healthz` dilakukan dari container probe di jaringan yang sama.

## ADR-010: Varian tuned dilaporkan terpisah dari default

**Status:** Diterima. **Keputusan:** hasil utama tetap memakai konfigurasi default idiomatik. Satu varian `tuned` per stack dijalankan sebagai skenario P1 S13 pada S3, S4, dan S8, dan dilaporkan di kolom terpisah dengan label jelas.

**Konteks.** Pengguna memilih varian tuned. Default menjawab "apa yang didapat tim yang tidak menyetel apa pun", sedangkan tuned menjawab "seberapa jauh stack bisa didorong". Mencampur keduanya akan membuat kesimpulan tidak bisa dipertanggungjawabkan.

**Aturan varian.**

- Semua perubahan dicatat di `tuning/variants.yaml`, maksimal tiga per stack. Setiap perubahan harus didukung versi yang terpasang (diverifikasi dari dokumentasi resmi atau perilaku runtime, bukan ditebak), dijelaskan alasannya, dan punya padanan di stack lain bila ada.
- Kandidat Go: `GOMEMLIMIT` sekitar 80% batas memori container dan `GOGC` lebih tinggi (menukar memori dengan GC yang lebih jarang).
- Kandidat Swift: jumlah event loop 2 kali CPU sebagai pembanding terhadap 1 kali CPU, dan flag compiler tambahan hanya bila didokumentasikan aman dan terbukti tersedia. Flag yang mematikan pemeriksaan keamanan (misalnya `-Ounchecked`) tidak dipakai.
- Sapuan ukuran pool koneksi (total 8, 16, 32, 64, sama untuk kedua stack) pada S3 dan S8, untuk melihat titik saturasi terhadap ukuran pool.
- Varian dipilih lewat `VARIANT=default` atau `VARIANT=tuned` dan dijalankan dari file Compose override (`docker-compose.tuned.yml`), sehingga default tidak pernah berubah.

**Konsekuensi.**

- Jumlah run bertambah. Pada laptop, sapuan pool memakai `REPEATS` yang sama dan bisa dibatasi lewat `SCENARIO`.
- Laporan menampilkan default dan tuned berdampingan beserta selisihnya, dan kesimpulan utama hanya bersumber dari default.
- Setiap perubahan tuned yang tidak bisa diverifikasi dibuang dan dicatat di Deviasi.

**Alternatif yang ditolak.** Menjadikan tuned sebagai default (menyembunyikan perilaku idiomatik). Menyetel hanya satu sisi (bias).

## ADR-011: Profiling di run terpisah, bukan saat pengukuran

**Status:** Diterima. **Keputusan:** profiling CPU dan alokasi dijalankan sebagai run terpisah (`make profile`) pada S8 dengan laju tetap 50% RPS saturasi, dengan aplikasi berjalan native di macOS. Hasilnya dipakai untuk menjelaskan selisih, bukan sebagai angka perbandingan.

**Konteks.** Pengguna memilih profiling untuk memahami kenapa angka berbeda. Profiler menambah overhead, sehingga tidak boleh aktif saat run pengukuran. Go menyediakan `net/http/pprof` di pustaka standar. Di macOS, perintah `sample` tersedia bawaan untuk mengambil sampel stack proses, dan Instruments (lewat `xctrace`) tersedia bila Xcode terpasang.

**Desain.**

- Aplikasi dijalankan native (`go-run` dan `swift-run`, konfigurasi `release`), Postgres tetap di Docker lewat port yang dipublikasikan ke localhost, dan k6 di container menembak aplikasi lewat `host.docker.internal`.
- Go: endpoint pprof hanya aktif bila `PROFILE=1`, di port admin 6060. Profil CPU 45 detik, serta snapshot heap, alokasi, dan goroutine, disimpan dalam format `.pb.gz` beserta tampilan SVG.
- Swift: `sample <pid> 45` untuk call tree teks, dan Instruments Time Profiler lewat `xctrace` sebagai opsi bila tersedia.
- Keluaran di `results/profiles/<app>/<skenario>/`. Laporan memuat 10 fungsi teratas per stack dari data profil dan tautan ke file mentah.

**Konsekuensi.**

- Profil berasal dari proses native di macOS, jadi tidak sebanding secara absolut dengan hasil container, dan laporan memberi label "penjelasan, bukan perbandingan".
- Laporan tidak boleh menyimpulkan penyebab selisih secara otomatis. Narasi hanya ditulis bila didukung langsung oleh data profil.
- Profiling Swift butuh toolchain native yang sama dengan ADR-008.

**Alternatif yang ditolak.** Profiling selama run pengukuran (merusak angka). `perf` di VM Docker Desktop (akses kernel dan simbol tidak dijamin tersedia).

## ADR-012: Base image runtime Distroless atau Alpine

**Status:** Diterima. **Keputusan:** image runtime semua komponen buatan kita memakai Distroless atau Alpine, tanpa Ubuntu atau Debian penuh. Default-nya flavor `distroless`, dan flavor `alpine` tersedia lewat variabel `IMAGE_FLAVOR`. Tahap build bebas memilih image apa pun.

**Konteks.** Pengguna meminta Distroless atau Alpine. Go dengan CGO nonaktif menghasilkan binary statis, jadi cocok untuk Distroless `static` (varian `static-debian13` tercatat tersedia menurut [artikel perbandingan image](https://oneuptime.com/blog/post/2026-01-16-docker-reduce-image-size/markdown)). Swift berbeda: forum Swift menyebut Alpine bisa dipakai untuk aplikasi Vapor bila dikompilasi dengan Musl SDK (Static Linux SDK) ([diskusi](https://forums.swift.org/t/what-is-the-smallest-docker-container-to-run-a-vapor-app/88507)). Opsi lain adalah Distroless berbasis glibc dengan `--static-swift-stdlib`, yang belum terbukti cukup untuk Vapor dan Fluent sehingga harus diverifikasi.

**Pilihan per stack (diverifikasi agen saat setup).**

| Komponen | Flavor `distroless` (default) | Flavor `alpine` (opsional) | Catatan |
| --- | --- | --- | --- |
| Go | `gcr.io/distroless/static-debian13:nonroot` (atau tag debian12 bila varian arm64 tidak ada) | Alpine stabil terbaru dengan binary statis yang sama | Tanpa libc, jadi libc tidak memengaruhi performa |
| Swift | `gcr.io/distroless/cc-debian13:nonroot` (glibc) dengan binary `--static-swift-stdlib` | Alpine dengan binary dari Static Linux SDK (musl) | Bila glibc gagal, fallback ke Alpine musl dan hasil diberi label musl |
| Postgres | `postgres:<versi>-alpine` | sama | Tidak ada Distroless untuk Postgres |
| k6 dan sampler | Image resmi k6 dan Alpine kecil untuk sampler | sama | Bukan bagian yang diukur |

**Aturan.**

- Aplikasi berjalan sebagai pengguna non-root. Image Distroless tidak punya shell, jadi health check dilakukan dari luar (probe di jaringan Docker), bukan lewat `docker exec` atau perintah shell di dalam image.
- Benchmark performa memakai flavor default. Bila Swift terpaksa memakai Alpine musl, laporan memberi label dan menjelaskan risikonya, karena alokator memori musl berbeda dengan glibc dan bisa memengaruhi performa dan memori.
- `make bench IMAGE_FLAVOR=alpine` menjalankan benchmark yang sama pada flavor Alpine. S12 mengukur ukuran image dan startup untuk kedua flavor bila keduanya berhasil dibangun.
- Tag, dukungan arm64, dan kecocokan library dibuktikan dengan menjalankan binary di image tersebut, bukan diasumsikan.

**Konsekuensi.**

- Debugging di dalam container lebih sulit (tanpa shell). Log dan endpoint admin tetap tersedia.
- Ukuran image dan startup menjadi hasil terukur, bukan angka dari image Ubuntu.
- Beban kerja agen bertambah: dua flavor, dua jalur build Swift (glibc dan musl).

**Alternatif yang ditolak.** `scratch` (tanpa sertifikat CA dan pengguna non-root). Image Ubuntu atau Debian penuh (tidak sesuai permintaan). Memaksa Swift ke Alpine musl sebagai default (risiko alokator musl menyamarkan perbandingan).

## ADR-013: Developer Experience, apa yang diukur dan cara menyimpulkannya

**Status:** Diterima. **Keputusan:** Developer Experience (DX) dinilai dari lima pengukuran terstruktur (DX1 sampai DX5) ditambah build time (ADR-008) dan startup (ADR-009). Kesimpulan hanya dinyatakan bila perbedaan melampaui variasi antar ulangan, dan faktor yang tidak terukur dicatat terpisah dengan label jelas.

**Konteks.** Pengguna ingin kesimpulan tentang DX. DX sebagian besar subjektif, jadi bagian yang bisa diukur harus dipisahkan tegas dari opini. Tanpa aturan, kesimpulan DX mudah berubah jadi selera.

**Pengukuran.**

| ID | Metrik | Cara ukur | Sifat |
| --- | --- | --- | --- |
| DX1 | Edit sampai siap | Dari satu file diubah sampai `/healthz` merespons 200 pada proses native (build B2 konfigurasi dev ditambah start proses) | Kuantitatif |
| DX2 | Waktu test suite | Suite paritas dengan sedikitnya 20 kasus yang sama (validasi, JSON, handler dengan repositori palsu). `go test ./...` vs `swift test`, dalam kondisi cache kosong dan hangat | Kuantitatif |
| DX3 | Ukuran kode dan dependency | Baris kode non-kosong non-komentar, jumlah file, dependency langsung dan transitif, ukuran cache dependency | Kuantitatif, deskriptif |
| DX4 | Diagnostik compiler | Tiga mutasi baku (tipe tidak cocok, simbol tidak terdefinisi, error tidak ditangani). Keluaran compiler disimpan apa adanya, dengan jumlah baris dan apakah menunjuk lokasi yang benar | Kualitatif |
| DX5 | Onboarding | Dari clone bersih sampai request pertama sukses: jumlah perintah, jumlah prasyarat yang harus dipasang, dan waktu (B1 dev ditambah start native) | Campuran |

**Aturan kesimpulan.**

- Satu stack dinyatakan lebih baik pada sebuah metrik hanya bila rentang minimum sampai maksimum kedua stack tidak tumpang tindih dan selisih median lebih dari 5%. Selain itu hasilnya "setara".
- Setiap klaim di laporan menunjuk ke tabel atau metrik yang mendukungnya.
- DX4 tidak diubah menjadi skor. Laporan menampilkan contoh keluaran dan observasi faktual saja.
- Faktor yang tidak diukur (kematangan ekosistem dan library, dukungan IDE dan debugging, ketersediaan engineer, stabilitas rilis seperti transisi Vapor 4 ke 5) ditulis di bagian terpisah "Tidak diukur", dengan sumber, tanpa bobot dalam kesimpulan.

**Konsekuensi.**

- Suite test paritas menambah pekerjaan di kedua aplikasi, dan framework test Swift (Swift Testing atau XCTest) dipilih satu dan dicatat.
- DX terukur bukan keseluruhan DX. Laporan menyatakan batas itu secara eksplisit.

**Alternatif yang ditolak.** Skor DX tunggal berbobot (bobot bersifat opini). Survei pengguna (di luar lingkup dan tidak bisa diulang).

## ADR-014: Skalabilitas dan arsitektur kode (monorepo modular)

**Status:** Diterima. **Keputusan:** repo tetap monorepo, kedua aplikasi disusun modular dengan lapisan yang setara, dan skalabilitas dinilai lewat tiga lensa: SC1 skala vertikal (skenario S14), SC2 skala konkurensi (turunan tahap A), dan SC3 skala basis kode (eksperimen M1, membandingkan topologi satu modul dengan banyak modul).

**Konteks.** Pengguna menyebut "monorepo atau modular architecture" sebagai contoh kesimpulan skalabilitas. Saya menafsirkannya dalam dua arti: cara menyusun kode kedua aplikasi, dan bagaimana biaya build serta pengembangan membesar saat basis kode tumbuh. Tafsiran ini dicatat sebagai asumsi dan bisa diubah.

**Arsitektur kode yang setara.**

| Lapisan | Go | Swift |
| --- | --- | --- |
| Domain (model dan validasi) | `internal/domain` | target `Domain` |
| Penyimpanan (repositori ORM) | `internal/store` (GORM) | target `Persistence` (Fluent) |
| HTTP (route, handler, middleware) | `internal/httpapi` (chi) | target `HTTPAPI` (Vapor) |
| Platform (konfigurasi, logging, pool) | `internal/platform` | target `Platform` |
| Entry point | `cmd/server` | target executable `App` |

Arah dependency satu arah (HTTP ke Store ke Domain, dengan Platform dipakai dari atas) dan tanpa dependency melingkar. Go memakai satu module (idiomatik) dan Swift memakai satu paket SwiftPM dengan banyak target.

**Tiga lensa skalabilitas.**

- **SC1 skala vertikal (S14):** batas CPU aplikasi 1, 2, dan 3 (`SCALE_CPUS`), dengan `GOMAXPROCS` dan jumlah event loop sama dengan CPU dan pool koneksi 8 kali CPU. Dijalankan pada S3 dan S8 tahap A. Efisiensi skala dihitung sebagai RPS(n) dibagi (n kali RPS(1)). Run ditandai "terbatas DB" bila CPU Postgres mencapai 90% atau lebih, karena VM 8 vCPU membatasi ruang.
- **SC2 skala konkurensi:** turunan dari tahap A, yaitu kemiringan memori puncak per 100 koneksi virtual, pertumbuhan thread per koneksi, dan titik lutut latensi.
- **SC3 skala basis kode (M1):** generator membuat proyek sintetis dengan N modul (default 1, 5, dan 20, serta 50 opsional lewat `MODULES`). Tiap modul berisi model, validasi, dan handler sekitar 100 baris, dan bergantung hanya pada modul inti. Dua topologi dibandingkan: T1 satu module atau paket (Go: satu module dengan N package, Swift: satu paket dengan N target) dan T2 banyak module atau paket (Go: N module dalam `go.work`, Swift: N paket lokal). Build yang diukur: B3 (dependency ter-cache), B2-leaf (ubah satu modul daun), dan B2-core (ubah modul inti). Native macOS, cache terisolasi, konfigurasi dev.

**Aturan kesimpulan.** Aturan ADR-013 berlaku (tidak tumpang tindih dan selisih median lebih dari 5%). Rekomendasi monorepo atau modular bersifat kondisional dan hanya mencakup rentang N yang diuji, misalnya "untuk stack X pada N modul, topologi T mengurangi waktu B2-leaf sebesar Y%". Laporan wajib menyebut batas: kode sintetis, satu mesin, dan laptop.

**Konsekuensi.**

- Ada pekerjaan tambahan untuk generator proyek sintetis, dan build Swift dengan banyak target atau paket bisa lama. Default N dibatasi hingga 20 di laptop, dan orkestrator mencetak estimasi durasi sebelum mulai.
- Hasil M1 menjelaskan biaya struktur kode, bukan kualitas arsitektur.
- S14 hanya sampai 3 CPU karena VM Docker berukuran 8 vCPU, sehingga kesimpulan skala vertikal terbatas pada rentang 1 sampai 3 core.

**Alternatif yang ditolak.** Mengukur kode produksi nyata (tidak tersedia). Hanya mengamati aplikasi uji (tidak menunjukkan pertumbuhan basis kode).
