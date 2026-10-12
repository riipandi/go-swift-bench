# PRD: Benchmark Backend Go vs Swift

Oct 13, 2026 · @Aris Ripandi

PRD versi 4 ini membandingkan dua stack backend yang melayani API CRUD identik di atas Postgres yang sama, dijalankan di MacBook Pro M2 Pro (16 GB) dengan logging aktif, seed data deterministik yang sama, k6 sebagai load generator, dan Makefile sebagai satu pintu masuk. Versi ini menambah pengukuran build time, ukuran image dan startup, varian tuned, dan profiling, lalu base image Distroless atau Alpine serta kesimpulan Developer Experience dan skalabilitas (termasuk monorepo vs modular). Keputusan dan alasannya ada di [ADR](https://claude.ai/code/artifact/9aaf3cee-ddfd-49ff-b693-f683d54856bf).

## Ringkasan dan tujuan

|  | Stack Go | Stack Swift |
| --- | --- | --- |
| Bahasa | Go 1.27.2 | Swift 6.4.0 |
| Router / framework | chi v5 | Vapor 4 (stabil) |
| ORM | GORM | Fluent 4 |
| Logging | LogLayer v3 dengan transport `log/slog` | SwiftLog bawaan Vapor |
| Database | Postgres via Docker Compose (sama) | Postgres via Docker Compose (sama) |
| Load generator | k6 v2 (sama) | k6 v2 (sama) |
| Host uji | MacBook Pro M2 Pro, 16 GB. Benchmark beban di Docker Desktop (container linux/arm64) | sama |
| Build time | Diukur native di macOS (B1, B2, B3) | Diukur native di macOS (B1, B2, B3) |
| Base image runtime | Distroless (default) atau Alpine, non-root | Distroless (default) atau Alpine, non-root |

Tujuan, berurutan dari yang terpenting:

1. Mengukur RPS maksimum per skenario pada batas latensi yang disepakati (p99 di bawah ambang SLO).
2. Mengukur resource usage rinci: CPU (user vs system), memori (rata-rata, puncak, pertumbuhan), thread, file descriptor, network, dan I/O disk.
3. Menghitung efisiensi: RPS per core CPU dan RPS per MB memori.
4. Mengukur build time (bersih, inkremental, dependency ter-cache), ukuran image dan binary, waktu start, dan latensi request pertama.
5. Mengukur biaya logging: selisih CPU, memori, dan latensi antara mode log `quiet` dan `access`.
6. Menyimpulkan Developer Experience (edit sampai siap, waktu test, ukuran kode, diagnostik compiler, onboarding) dengan pemisahan tegas antara yang terukur dan yang opini.
7. Menyimpulkan skalabilitas: skala vertikal 1 sampai 3 core, pertumbuhan resource terhadap konkurensi, dan pertumbuhan biaya build terhadap jumlah modul (monorepo satu modul vs banyak modul).
8. Menunjukkan seberapa jauh tiap stack bisa didorong (varian tuned) dan menjelaskan selisih lewat profiling, terpisah dari hasil default.
9. Menghasilkan hasil yang bisa diulang dan mudah dijalankan: versi dikunci, seed data sama, lingkungan dicatat otomatis, satu perintah `make` untuk tiap tugas.

Pembaca hasil adalah engineer yang memilih stack backend. Mereka butuh angka yang adil dan konteks batasannya, bukan pemenang tunggal. Karena host adalah laptop, hasil dibaca sebagai perbandingan relatif Go vs Swift, bukan angka absolut server.

### Perubahan dari versi 3

- Image runtime memakai Distroless (default) atau Alpine lewat `IMAGE_FLAVOR` (ADR-012).
- Kesimpulan Developer Experience dari DX1 sampai DX5 dengan aturan penarikan kesimpulan (ADR-013).
- Skalabilitas dinilai lewat S14 (skala vertikal), SC2 (skala konkurensi), dan eksperimen M1 (satu modul vs banyak modul), dan kedua aplikasi disusun sebagai monorepo modular dengan lapisan setara (ADR-014).
- Bagian Kesimpulan di laporan disusun dari data dengan aturan ketat, dan faktor yang tidak terukur dipisahkan.

### Perubahan dari versi 2

- Build time diukur native di macOS dengan tiga skenario dan cache terisolasi (ADR-008).
- Ukuran image, startup, dan cold start ditambahkan sebagai skenario S12 (ADR-009).
- Varian tuned per stack ditambahkan sebagai skenario S13 dan dilaporkan terpisah dari default (ADR-010).
- Profiling di run terpisah dengan aplikasi native ditambahkan, hanya untuk menjelaskan selisih (ADR-011).
- Varian `synchronous_commit=on` dan dataset lebih besar dari RAM tidak masuk lingkup versi ini.

### Perubahan dari versi 1 (sudah berlaku di versi 2)

- Host diganti MacBook M2 Pro dengan profil `mac-m2` (ADR-002), logging dua mode dengan S11 (ADR-004), seed data deterministik dengan fixture dan checksum (ADR-005).
- k6 v2 dikunci sebagai alat beban, sampler resource pindah ke container sidecar, dan Makefile menjadi pintu masuk (ADR-003, ADR-006, ADR-007).

## Hasil riset ekosistem

Go 1.27 (Agustus 2026) dan Swift 6.4 (15 September 2026) sama-sama sudah rilis, tetapi Vapor 5 masih beta, sehingga stack Swift yang layak dijadikan dasar kesimpulan adalah Vapor 4 dengan Fluent 4.

| Komponen | Status per 13 Okt 2026 | Implikasi untuk benchmark |
| --- | --- | --- |
| [Go 1.27](https://go.dev/doc/go1.27) | Rilis Agustus 2026. Menambah generic methods dan paket SIMD eksperimental. Menurut [ringkasan media atas draft release notes](https://northeasttimes.com/?p=159806): mesin JSON baru (unmarshal jauh lebih cepat, marshal setara) dan alokasi kecil di bawah 80 byte hingga 30% lebih murah. | Perubahan menyentuh jalur panas API (JSON, alokasi). Pakai default stdlib dan catat versi persis. Patch 1.27.2 belum bisa saya verifikasi. |
| chi v5 | Rilis terbaru yang saya temukan: v5.3.1 (Juli 2026, dari [PR dependabot](https://github.com/coder/coder-logstream-kube/pull/215)). | Kunci ke v5.3.x. |
| GORM | gorm.io/gorm v1.31.2 dan gorm.io/driver/postgres v1.6.2, berbasis pgx v5 ([sumber](https://github.com/InWheelOrg/inwheel-api/pull/120)). | Atur `PrepareStmt` dan pool `database/sql` secara eksplisit. |
| [LogLayer for Go](https://go.loglayer.dev/) | Modul `go.loglayer.dev/v3`. Transport [`log/slog`](https://go.loglayer.dev/transports/slog.html) membungkus `*slog.Logger` (`go.loglayer.dev/transports/slog/v3`). Middleware [`loghttp`](https://go.loglayer.dev/integrations/loghttp.html) (`go.loglayer.dev/integrations/loghttp/v3`) bekerja dengan chi: menurunkan logger per request berisi `requestId`, `method`, `path`, lalu menulis baris "request completed" berisi status, durasi, dan byte. | Dipakai sebagai lapisan logging Go. Biaya lapisan ini ikut terukur. |
| Logging Vapor | Berbasis [SwiftLog](https://docs.vapor.codes/basics/logging/). Level default `info`, diatur lewat `LOG_LEVEL` atau flag `--log`, dikonfigurasi dengan `bootstrap(from:)`. `req.logger` membawa metadata `request-id`. `RouteLoggingMiddleware` tersedia untuk log akses. | Dipakai apa adanya. Handler bawaan mencetak teks, bukan JSON. |
| k6 | Seri v2: v2.0.0 rilis 11 Mei 2026 dan v2.3.0 tercatat terbaru per 28 September 2026 ([catatan migrasi](https://qaskills.sh/blog/k6-2-migration-guide-breaking-changes), sumber pihak ketiga). Executor [`constant-arrival-rate`](https://grafana.com/docs/k6/latest/using-k6/scenarios/executors/constant-arrival-rate.md) bersifat open-model. | Kunci image `grafana/k6` ke versi 2.x yang diverifikasi saat setup. |
| Swift 6.4 | Rilis 15 September 2026. Swift Build jadi default di SwiftPM, Subprocess 1.0, tipe noncopyable baru (`UniqueArray`, `Iterable`), parsing URL Foundation hingga 4x lebih cepat ([InfoQ](https://www.infoq.com/news/2026/09/swift-6-4-released/), [InfoWorld](https://www.infoworld.com/article/4225734/apple-touts-simpler-and-clearer-code-with-swift-6-4.html)). | Sistem build berubah: catat waktu build dan ukuran image. Foundation lebih cepat bisa memengaruhi jalur JSON dan URL. |
| Vapor 4 | Masih versi stabil resmi: 306 rilis dalam sekitar 6,5 tahun, dan tetap menerima perbaikan serta patch keamanan setelah Vapor 5 rilis ([Vapor blog](https://blog.vapor.codes/posts/vapor-5-beta/)). | Stack Swift utama benchmark ini. |
| Vapor 5 | Beta 1 dirilis 15 September 2026. Penuh async/await, server HTTP baru, body streaming-first, wajib Swift 6.4 (dan macOS 26 untuk build native). WebSocket dan kompresi belum ada. Tim Vapor tidak menyarankan produksi. Integrasi Fluent masih lewat FluentKit langsung di template ([Vapor blog](https://blog.vapor.codes/posts/vapor-5-beta/)). | Varian opsional eksperimental (P2). Tidak dipakai sebagai dasar kesimpulan utama. |

### Perbedaan arsitektur yang memengaruhi desain uji

- **Konkurensi:** Go memakai scheduler goroutine dengan satu pool koneksi global di `database/sql`. Vapor memakai event loop SwiftNIO, dan pool Fluent Postgres dihitung per event loop (`maxConnectionsPerEventLoop`). Total koneksi harus disamakan secara eksplisit.
- **Memori:** Go punya garbage collector konkuren, sedangkan Swift memakai ARC tanpa GC. Pola memori (puncak, pertumbuhan, pelepasan) wajib diamati selama soak test, bukan hanya rata-rata.
- **Jumlah thread:** sejak Go 1.25, `GOMAXPROCS` mengikuti batas CPU cgroup. Jumlah event loop Vapor harus diset eksplisit sama dengan batas CPU container.
- **JSON:** Go memakai `encoding/json` bawaan, Vapor memakai Foundation `JSONEncoder` dan `JSONDecoder`. Skenario JSON tanpa database memisahkan biaya ini dari biaya ORM.
- **Logging:** Go melewati dua lapisan (LogLayer lalu slog), Vapor satu lapisan (SwiftLog). Mode `quiet` dan `access` memisahkan biaya baseline dari biaya menulis log.
- **Apple Silicon:** image resmi Go dan Swift tersedia untuk arm64, jadi seluruh uji berjalan native arm64 di dalam VM Docker, tanpa emulasi amd64.

### Keputusan versi

- **Stack utama:** Go 1.27.2, chi v5.3.x, GORM v1.31.x dan driver Postgres v1.6.x, LogLayer v3. Swift 6.4.0, Vapor 4 (rilis 4.x terbaru), Fluent 4, fluent-postgres-driver 2.x.
- **Load generator:** k6 seri v2, versi persis dikunci saat setup.
- **Varian opsional:** Vapor 5 beta, dijalankan hanya jika stack utama sudah lulus semua kriteria penerimaan, dan hasilnya diberi label eksperimental.
- **Postgres:** rilis stabil terbaru dengan setidaknya satu patch, dikunci dengan digest image dan dicatat di laporan.

### Belum terverifikasi (agen wajib cek saat setup)

1. Tag Docker `golang:1.27.2`. Bila tidak ada, pakai tag 1.27.x terbaru dan catat hasil `go version`.
2. Tag image Swift 6.4 untuk arm64 (pola `swift:6.4-noble` dan varian slim untuk runtime).
3. Nomor versi Vapor 4, Fluent 4, dan fluent-postgres-driver terbaru yang kompatibel dengan Swift 6.4.
4. Nomor patch chi, GORM, pgx, dan LogLayer v3 terbaru saat `go get` dijalankan.
5. Tag image `grafana/k6` 2.x untuk arm64.
6. Jalur cgroup container di Docker Desktop VM, supaya sampler bisa membacanya.

Catatan sumber: posting Vapor 5 Beta, halaman LogLayer (beranda, transport slog, loghttp), dan dokumentasi logging Vapor saya buka atau kutip langsung. Sumber lain saya ambil dari kutipan hasil pencarian.

## Ruang lingkup

Benchmark mencakup API CRUD berbasis ORM di Postgres dengan logging aktif, diukur lewat HTTP dari container k6, ditambah pengukuran build time native, ukuran dan startup, varian tuned, dan profiling, semuanya dijalankan lewat Makefile di MacBook M2 Pro. Hal lain di luar itu tidak termasuk.

**Masuk lingkup**

- Dua aplikasi dengan kontrak HTTP identik: `go-app` dan `swift-app`, disusun sebagai monorepo modular dengan lapisan setara.
- Logging terstruktur di kedua aplikasi (LogLayer + slog untuk Go, SwiftLog bawaan untuk Vapor) dengan mode `quiet` dan `access`.
- Satu Postgres dengan skema, seed deterministik, indeks, dan konfigurasi sama, ditambah fixture kecil untuk uji kontrak.
- Image runtime Distroless (default) atau Alpine (opsional) lewat `IMAGE_FLAVOR`.
- Skenario P0 (S1 sampai S8) dan P1 (S9 sampai S14), dijalankan dengan k6 v2.
- Build time native di macOS: B1 bersih tanpa cache, B2 build ulang setelah ubah satu file, B3 dependency ter-cache, dalam konfigurasi `dev` dan `release`.
- Ukuran image dan binary, waktu start sampai siap, latensi request pertama, dan memori idle (S12).
- Varian tuned per stack dan sapuan ukuran pool (S13), dilaporkan terpisah dari default.
- Developer Experience DX1 sampai DX5, termasuk suite test paritas dan mutasi untuk diagnostik compiler.
- Skalabilitas: skala vertikal 1 sampai 3 core (S14), skala konkurensi (SC2), dan eksperimen skala basis kode M1 (satu modul vs banyak modul).
- Profiling CPU dan alokasi di run terpisah untuk menjelaskan selisih.
- Bagian Kesimpulan di laporan untuk DX dan skalabilitas, dengan aturan penarikan kesimpulan yang ketat.
- Pengumpulan metrik resource per container lewat sampler sidecar, dan metrik Postgres.
- Makefile untuk cek prasyarat, database, build dan run tiap aplikasi (native dan container), uji kontrak, semua benchmark, laporan, dan bersih-bersih.

**Di luar lingkup**

- Autentikasi, caching, message queue, WebSocket, HTTP/2 dan HTTP/3, TLS.
- Pengiriman log ke layanan eksternal, tracing, dan metrik aplikasi (Prometheus). Log hanya ke stdout.
- Waktu build image Docker.
- Varian `synchronous_commit=on` dan dataset yang lebih besar dari RAM Postgres (tidak dipilih untuk versi ini).
- Skala horizontal (banyak replika di belakang load balancer) dan skala vertikal di atas 3 core, karena VM Docker berukuran 8 vCPU.
- Skor Developer Experience tunggal berbobot, survei pengguna, dan penilaian arsitektur selain biaya build (M1).
- Deployment cloud, Kubernetes, dan tuning khusus per bahasa di luar varian tuned yang didefinisikan.
- Benchmark di server Linux. PRD ini bisa dipakai ulang dengan profil `linux-medium`, tetapi hasil dari Mac tidak boleh dicampur dengan hasil dari mesin lain.
- Perbandingan produktivitas developer atau kualitas kode di luar metrik DX yang didefinisikan.
- Kesimpulan umum tentang "bahasa mana lebih baik". Hasil hanya berlaku untuk stack, versi, host, dan beban yang diuji.

## Arsitektur dan lingkungan uji

Semua komponen berjalan sebagai container linux/arm64 di Docker Desktop pada Mac, dengan batas resource per container, dan hanya satu aplikasi yang aktif pada satu waktu agar tidak saling mengganggu.

| Komponen | Peran | Berkomunikasi dengan | Catatan isolasi |
| --- | --- | --- | --- |
| `postgres` | Database bersama | Menerima koneksi dari aplikasi yang aktif | `cpuset` sendiri, data di named volume, `max_connections` dikunci, `pg_stat_statements` aktif |
| `go-app` | Aplikasi Go (chi + GORM + LogLayer) | Postgres | Batas CPU dan memori sama dengan `swift-app` |
| `swift-app` | Aplikasi Swift (Vapor 4 + Fluent 4) | Postgres | Batas CPU dan memori sama dengan `go-app` |
| `k6` | Load generator | Aplikasi yang sedang diuji, lewat jaringan Docker internal | `cpuset` sendiri, tidak lewat port publish |
| `sampler` | Membaca cgroup dan `/proc` tiap 1 detik, menulis CSV | Container yang sedang diuji | `pid: host` dan `cgroup: host` dengan akses baca, batas resource kecil |
| `monitoring` (profil opsional) | cAdvisor, Prometheus, Grafana | Semua container | Mati secara default agar tidak menambah beban saat benchmark |

### Profil resource

Profil dipilih lewat variabel `PROFILE`. Default-nya `mac-m2`, dan `make doctor` menolak melanjutkan bila VM Docker lebih kecil dari yang disyaratkan profil.

| Profil | VM Docker | CPU aplikasi | CPU Postgres | CPU k6 | Memori aplikasi | Memori Postgres | Memori k6 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `mac-m2` (default) | 8 vCPU, 8 GB | 2 | 2 | 2 | 1 GB | 2 GB | 1 GB |
| `linux-medium` (opsional) | host Linux 12 core | 4 | 4 | 4 | 2 GB | 4 GB | 2 GB |

### Syarat dan aturan di Mac

- MacBook Pro M2 Pro 16 GB, macOS dengan Docker Desktop (atau OrbStack bila pengguna memilihnya). Di Settings, Resources, VM diatur 8 vCPU dan 8 GB, sehingga macOS masih punya sedikitnya 2 core dan 8 GB.
- Semua image harus linux/arm64. Image amd64 yang berjalan lewat emulasi ditolak oleh `make doctor`.
- Data Postgres berada di named volume, bukan bind mount, agar I/O tidak melewati lapisan berbagi file dengan macOS.
- Charger tersambung, Low Power Mode mati, aplikasi berat lain ditutup, dan run dibungkus `caffeinate -dims`. Status thermal (`pmset -g therm`) dicatat sebelum dan sesudah run, dan run yang terkena throttling ditandai.
- Core M2 Pro terbagi performance dan efficiency dan dijadwalkan oleh macOS, jadi pinning ke core fisik tidak mungkin. `cpuset` hanya memisahkan vCPU di dalam VM.
- Setiap laporan mencatat `sw_vers`, model Mac, jumlah core, ukuran VM Docker, versi Docker, `ulimit -n`, dan digest semua image, serta memuat label "Apple Silicon, Docker Desktop VM: hasil relatif, bukan absolut".

### Pengukuran yang berjalan native di Mac

- Build time (B1 sampai B3) dan profiling berjalan native di macOS, bukan di VM Docker, dan tidak boleh berjalan bersamaan dengan beban Docker.
- Go 1.27.2 dan toolchain Swift 6.4 (Xcode 27 atau toolchain swift.org) harus terpasang native. `make doctor` memeriksanya dan menolak `build-bench` serta `profile` bila tidak ada, tanpa memasang apa pun otomatis.
- Saat profiling, Postgres di Docker dipublikasikan ke localhost dan k6 di container menembak aplikasi lewat `host.docker.internal`.
- Laporan memberi label bahwa angka build time dan profil berasal dari macOS native, sedangkan angka beban berasal dari container di VM Docker.

### Base image container

Image runtime semua komponen buatan kita memakai Distroless atau Alpine, tanpa Ubuntu atau Debian penuh, sedangkan tahap build bebas. Keputusan ada di ADR-012.

| Komponen | Flavor `distroless` (default) | Flavor `alpine` (opsional) |
| --- | --- | --- |
| Go | `gcr.io/distroless/static-debian13:nonroot` (atau tag debian12 bila varian arm64 tidak ada) | Alpine stabil terbaru dengan binary statis yang sama |
| Swift | `gcr.io/distroless/cc-debian13:nonroot` (glibc) dengan binary `--static-swift-stdlib` | Alpine dengan binary dari Static Linux SDK (musl) |
| Postgres | `postgres:<versi>-alpine` | sama |
| k6 dan sampler | Image resmi k6, dan Alpine kecil untuk sampler | sama |

- Flavor dipilih lewat `IMAGE_FLAVOR` (default `distroless`). Benchmark performa memakai flavor default, dan `make bench IMAGE_FLAVOR=alpine` menjalankan benchmark yang sama pada flavor Alpine.
- Aplikasi berjalan sebagai pengguna non-root. Distroless tidak punya shell, jadi health check dilakukan dari container probe di jaringan Docker.
- Bila Swift tidak bisa berjalan di Distroless glibc dan terpaksa memakai Alpine musl, laporan memberi label musl dan menjelaskan risikonya (alokator memori musl berbeda dengan glibc).
- Tag, dukungan arm64, dan kecocokan library dibuktikan dengan menjalankan binary di image tersebut.

## Spesifikasi aplikasi

Kedua aplikasi mengekspos sembilan endpoint dengan bentuk JSON yang sama, membaca database yang sama persis, mengakses data hanya lewat ORM masing-masing (GORM dan Fluent), dan mencatat log dengan pustaka masing-masing.

### Skema database

```sql
users    (id bigserial PK, name text, email text UNIQUE, created_at timestamptz)        -- 10.000 baris
orders   (id bigserial PK, user_id bigint FK -> users, status text, total_cents int,
          note text, created_at timestamptz, updated_at timestamptz)                   -- 500.000 baris (rata-rata 50 per user)
payments (id bigserial PK, order_id bigint FK -> orders, amount_cents int, created_at timestamptz)  -- kosong saat awal

INDEX orders (user_id, created_at DESC)
INDEX orders (status, id)
```

Skema dibuat hanya oleh `db/schema.sql`. Aplikasi tidak boleh membuat atau mengubah tabel (tanpa auto-migrate di GORM maupun migrasi Fluent), dan model memetakan nama tabel dan kolom secara eksplisit.

### Seed data

Detail keputusan ada di ADR-005. Ringkasannya:

| Lapis | Isi | Dipakai untuk |
| --- | --- | --- |
| Fixture (`db/fixtures/`) | 20 user dan 100 order bernilai tetap, termasuk user tanpa order, semua status, `note` kosong dan `note` 200 karakter | Uji kontrak dengan respons acuan (golden JSON) |
| Seed benchmark (`db/seed.sql`) | 10.000 user dan 500.000 order dari `generate_series` dan hash deterministik | Semua skenario beban |

- `user_id` pada order condong ringan (user terpadat sekitar 250 order, rata-rata 50). Status: 20% `pending`, 50% `paid`, 20% `shipped`, 10% `cancelled`.
- `created_at` tersebar 365 hari dari tanggal tetap, `total_cents` antara 500 dan 500.000.
- Seed mengekspor `loadtest/data/*.json` (ID user, ID order, ID order `pending`) agar k6 hanya memilih ID yang ada.
- Setelah seed, skrip mencetak checksum per tabel dan menjalankan `VACUUM ANALYZE`. Database hasil seed disimpan sebagai template, dan reset antar run memakai `CREATE DATABASE ... TEMPLATE`.

### Logging

Detail keputusan ada di ADR-004.

| Aspek | Go | Swift |
| --- | --- | --- |
| Pustaka | LogLayer v3 (`go.loglayer.dev/v3`) dengan transport slog (`go.loglayer.dev/transports/slog/v3`), handler teks `slog` ke stdout | SwiftLog bawaan Vapor lewat `LoggingSystem.bootstrap(from: &env)` |
| Middleware | `loghttp.Middleware` dipasang di chi, setelah `middleware.Recoverer` | `req.logger` bawaan, `RouteLoggingMiddleware(logLevel: .info)` hanya di mode `access` |
| Mode `quiet` (default) | Level `error`, baris akses tersaring | `LOG_LEVEL=error`, tanpa middleware log akses |
| Mode `access` | Level `info`, satu baris akses per request | `LOG_LEVEL=info` dan `RouteLoggingMiddleware` aktif |
| Konfigurasi | `LOG_MODE` (nilai quiet atau access) dan `LOG_FORMAT` (nilai text atau json) | `LOG_MODE` (nilai quiet atau access) diterjemahkan ke `LOG_LEVEL` dan middleware |

Setiap baris log akses memuat request ID, method, path, status, dan durasi. Log startup dan error selalu tertulis di kedua mode. Kedua aplikasi menulis ke stdout, dan container memakai driver log Docker `local` dengan rotasi.

### Kontrak endpoint

| Endpoint | Skenario | Query ke DB | Perilaku |
| --- | --- | --- | --- |
| `GET /healthz` | semua | 0 | Mengembalikan `{"status":"ok"}` |
| `GET /bench/json` | S1 | 0 | Objek JSON tetap sekitar 1 KB (20 field, satu array kecil), dibuat di memori |
| `POST /bench/echo` | S2 | 0 | Decode body JSON sekitar 1 KB bersarang, validasi, encode ulang sebagai respons |
| `GET /users/{id}` | S3 | 1 (PK) | Satu user, 404 bila tidak ada |
| `GET /users/{id}/orders?limit=20` | S4 | 1 (indeks user\_id) | 20 order terbaru, urut `created_at DESC, id DESC` |
| `GET /users/{id}?include=orders` | S5 | 2 | User beserta semua ordernya lewat eager loading (`Preload` dan `with`) |
| `POST /orders` | S6 | 1 (insert) | Validasi, simpan, kembalikan 201 dengan order baru |
| `PUT /orders/{id}` | S7 | 2 (baca lalu update) | Ubah `status` dan `updated_at`, 404 bila tidak ada |
| `POST /orders/{id}/pay` | S9 (P1) | transaksi | Dalam satu transaksi: update status order jadi `paid` dan insert baris `payments` |

Aturan kontrak yang berlaku untuk semua endpoint:

- Kunci JSON `snake_case`, timestamp RFC 3339 UTC, uang dalam sen (integer).
- Kesalahan validasi mengembalikan 400 dan resource tidak ada mengembalikan 404, keduanya dengan body `{"error":"<pesan>"}`.
- Validasi `POST /orders`: `user_id` positif, `total_cents` antara 0 dan 10.000.000, `status` salah satu dari `pending`, `paid`, `shipped`, `cancelled` (default `pending`), `note` maksimal 200 karakter.
- Tanpa TLS, tanpa kompresi, HTTP/1.1 keep-alive.

## Skenario dan profil beban

Tujuh skenario pertama memisahkan biaya per lapisan (framework, JSON, ORM, relasi, tulis), skenario campuran mendekati lalu lintas nyata, dan enam skenario P1 menguji transaksi, kestabilan memori, biaya logging, startup, varian tuned, dan skala vertikal.

| ID | Prioritas | Endpoint | Yang diisolasi | Distribusi request |
| --- | --- | --- | --- | --- |
| S1 | P0 | `GET /bench/json` | Overhead framework dan encode JSON | 100% |
| S2 | P0 | `POST /bench/echo` | Decode lalu encode JSON | 100% |
| S3 | P0 | `GET /users/{id}` | Baca by primary key lewat ORM | `id` dari `loadtest/data` |
| S4 | P0 | `GET /users/{id}/orders` | Query terindeks, urutan, dan mapping 20 baris | `id` user acak |
| S5 | P0 | `GET /users/{id}?include=orders` | Eager loading relasi (2 query, sampai sekitar 250 baris) | `id` user acak |
| S6 | P0 | `POST /orders` | Insert dengan validasi | `user_id` acak |
| S7 | P0 | `PUT /orders/{id}` | Update dengan baca lebih dulu | `id` order acak |
| S8 | P0 | Campuran | Beban realistis | 50% S3, 20% S4, 10% S5, 10% S6, 10% S7 |
| S9 | P1 | `POST /orders/{id}/pay` | Transaksi dua tulisan | `id` order berstatus `pending` |
| S10 | P1 | Campuran (S8) | Soak pada 70% RPS saturasi: pertumbuhan memori dan drift latensi | sama dengan S8 |
| S11 | P1 | Campuran (S8) | Biaya logging: S8 pada laju tetap 50% saturasi, mode `quiet` lalu `access` | sama dengan S8 |
| S12 | P1 | Container baru: /healthz lalu endpoint S1, S3, S4, S6 | Ukuran image, waktu start, latensi request pertama, memori idle | 10 ulangan per stack |
| S13 | P1 | S3, S4, S8 dengan VARIANT=tuned | Varian tuned dan sapuan ukuran pool koneksi (8, 16, 32, 64) | Sama dengan skenario asal |
| S14 | P1 | S3 dan S8 dengan CPU aplikasi 1, 2, 3 | Skala vertikal: RPS dan efisiensi terhadap jumlah core | Sama dengan skenario asal, tahap A |

Seluruh ID acak dipilih oleh k6 dari daftar hasil seed memakai PRNG ber-seed tetap, sehingga urutan request sama untuk kedua aplikasi.

### Tahap pengujian per skenario

Setiap titik ukur adalah satu invokasi k6 dengan keluaran ringkasan JSON (`--summary-export`). Keluaran per request tidak disimpan karena terlalu besar pada ribuan RPS.

| Tahap | Mode | `mac-m2` (default) | `linux-medium` | Keluaran |
| --- | --- | --- | --- | --- |
| Warm-up | Beban sedang | 20 detik, tidak dihitung | 30 detik, tidak dihitung | Mengisi cache Postgres, pool koneksi, dan alokator memori |
| A. Tangga konkurensi | Closed-loop (`constant-vus`) | 16, 32, 64, 128, 256 VU, masing-masing 10 detik ramp dan 30 detik steady | 8 sampai 512 VU, 15 detik ramp dan 60 detik steady | Kurva RPS vs konkurensi, titik saturasi |
| B. Laju tetap | Open-loop (`constant-arrival-rate`) | 25%, 50%, 75% dari RPS saturasi implementasi yang lebih lambat, masing-masing 60 detik | sama, 90 detik | Latensi dan resource usage pada throughput yang sama |
| C. Soak (S10) | Open-loop | 20 menit pada 70% RPS saturasi | 30 menit | Tren memori, thread, dan latensi |

Aturan pelaksanaan:

- **Titik saturasi** adalah RPS tertinggi dengan error rate di bawah 0,1% dan p99 di bawah ambang SLO (default 250 ms, bisa diubah lewat `SLO_P99_MS`).
- **Ulangan:** default 3 run per titik ukur di `mac-m2` (5 di `linux-medium`), bisa diubah lewat `REPEATS`. Urutan Go dan Swift diselang-seling dan diacak untuk meredam drift suhu dan noise host.
- **Kondisi awal tiap run:** container aplikasi di-restart, database direset dari template, dan statistik Postgres di-reset.
- **Validitas load generator:** run dibuang dan diulang bila CPU k6 melewati 80%, karena yang diukur bisa jadi k6, bukan aplikasi. Run juga ditandai bila status thermal Mac menunjukkan throttling.
- **Perkiraan durasi di `mac-m2`:** sekitar 7 menit per skenario per aplikasi per ulangan. Skenario inti (S1, S3, S4, S8) dengan 3 ulangan memakan sekitar 3 jam, dan semua skenario P0 sekitar 6 jam. Orkestrator mencetak estimasi dari konfigurasi sebelum mulai, dan `make bench-smoke` selesai di bawah 15 menit.

## Benchmark build time (native macOS)

Build time diukur native di macOS untuk tiga skenario dan dua konfigurasi, memakai direktori cache terisolasi, supaya mewakili pengalaman developer tanpa merusak cache global di Mac. Keputusan ada di ADR-008.

| ID | Kondisi awal | Go | Swift |
| --- | --- | --- | --- |
| B1 Build bersih tanpa cache | Semua cache kosong, termasuk dependency | `GOCACHE` dan `GOMODCACHE` baru dan kosong, lalu `go mod download` dan `go build` | `--scratch-path` dan `--cache-path` baru dan kosong, lalu `swift package resolve` dan `swift build` |
| B2 Build ulang setelah ubah 1 file | Cache hangat dan hasil build ada. Satu file diubah | `go build` | `swift build` |
| B3 Dependency ter-cache | Sumber dependency ada, artefak kompilasi dibuang | `go clean -cache` (module cache dipertahankan), lalu `go build` | `swift package clean` (checkouts dipertahankan), lalu `swift build` |

| Konfigurasi | Go | Swift |
| --- | --- | --- |
| `dev` | `go build` | `swift build` (debug) |
| `release` | `go build -trimpath -ldflags='-s -w'` | `swift build -c release` |

Aturan pengukuran:

- **Cache terisolasi:** `GOCACHE` dan `GOMODCACHE` untuk Go, serta `--scratch-path`, `--cache-path`, `--config-path`, dan `--security-path` untuk SwiftPM, diarahkan ke direktori sementara berakhiran `.noindex`. Cache global pengguna tidak boleh dihapus atau diubah.
- **File yang diubah di B2:** satu file di lapisan handler yang setara di kedua aplikasi (misalnya teks pesan di handler `/healthz`), dikembalikan seperti semula setelah tiap run. Hash binary harus berubah, sebagai bukti terjadi kompilasi ulang.
- **Paralelisme:** default toolchain, dicatat bersama jumlah core (`hw.ncpu`). Tidak ada tuning `-j`.
- **B1** dilaporkan sebagai total dan rincian (unduh dependency vs kompilasi), karena unduhan bergantung jaringan.
- **Alat ukur:** `/usr/bin/time -l` dibungkus skrip `tools/buildtime`, mencatat wall time, CPU user dan system, peak RSS, dan ukuran binary hasil build. Paralelisme efektif dihitung dari (user + system) dibagi wall.
- **Ulangan:** B1 sebanyak 3, B2 sebanyak 5, B3 sebanyak 3 (`BUILD_REPEATS`). Urutan Go dan Swift diselang-seling, ada jeda sampai status thermal normal (`pmset -g therm`), dan semuanya dibungkus `caffeinate -dims`.
- **Isolasi dari beban lain:** tidak ada container benchmark yang berjalan bersamaan, dan aplikasi berat lain ditutup. Build gagal membatalkan run.
- **Cache kompilasi SwiftPM:** agen memverifikasi bahwa fitur compilation caching tidak aktif di toolchain terpasang, agar B1 dan B3 tidak terbantu cache tersembunyi.

Syarat dan target:

- Go 1.27.2 dan toolchain Swift 6.4 harus terpasang native di Mac (Xcode 27 atau toolchain swift.org). `make doctor` menolak `build-bench` bila tidak ada, dan tidak memasang apa pun otomatis.
- Target: `build-bench` (semua), `build-bench-clean` (B1), `build-bench-incr` (B2), `build-bench-cached` (B3). Variabel: `BUILD_REPEATS` dan `BUILD_CONFIG` (dev, release, atau both).
- Waktu build image Docker tidak diukur.

Dasar riset: opsi SwiftPM `--scratch-path`, `--cache-path`, `--config-path`, dan `--security-path` ([contoh opsi](https://code.webartifex.biz/alexander/oh-my-zsh/raw/commit/041c35ffc8cd97dd6327f44e35fa777af6f8e845/plugins/swiftpm/_swift)), cache global SwiftPM di macOS dan [pitch compilation caching](https://forums.swift.org/t/pitch-compilation-caching-support-in-swiftpm/88079), serta Swift Build sebagai default di Swift 6.4 ([InfoWorld](https://www.infoworld.com/article/4225734/apple-touts-simpler-and-clearer-code-with-swift-6-4.html)). Belum terverifikasi dan wajib dicek agen: opsi SwiftPM di atas diterima oleh `swift build` dan `swift package resolve` di Swift 6.4, `--static-swift-stdlib` didukung atau tidak di macOS (build Linux di image tetap memakainya), dan compilation caching tidak aktif secara default.

## Ukuran image, startup, dan cold start (S12)

Skenario P1 S12 mengukur seberapa besar dan seberapa cepat siap tiap aplikasi sebagai container, dengan 10 ulangan per stack. Keputusan ada di ADR-009.

| Metrik | Cara ukur |
| --- | --- |
| Ukuran image dan binary | `docker image inspect` untuk ukuran dan jumlah layer, serta ukuran binary di dalam image |
| Waktu start sampai siap | Dari perintah membuat container (image sudah ada, Postgres sudah hidup) sampai respons 200 pertama dari `/healthz`, dengan polling tiap 10 ms dari container di jaringan yang sama |
| Latensi request pertama | Satu request pertama ke endpoint S1, S3, S4, dan S6 dalam urutan tetap, sebelum warm-up, dicatat per endpoint |
| Memori idle | Memori container 5 detik setelah siap, dan lagi setelah 100 request pertama |

- Tiap ulangan me-restart container dari awal dan mereset database dari template bila endpoint menulis data.
- Waktu start mencakup overhead pembuatan container Docker yang sama untuk kedua stack. Laporan menyebutkannya dan membandingkan selisih antar stack.
- Cache halaman OS sudah hangat karena image sudah ada, jadi "cold start" berarti proses baru, bukan unduh image.
- Target Makefile: `startup-bench`. Hasil ditulis ke `results/raw/startup/`.

## Varian tuned per stack (S13)

Hasil utama tetap memakai konfigurasi default, dan satu varian `tuned` per stack dijalankan terpisah pada S3, S4, dan S8 untuk melihat seberapa jauh tiap stack bisa didorong. Keputusan ada di ADR-010.

| Stack | Perubahan kandidat | Alasan |
| --- | --- | --- |
| Go | `GOMEMLIMIT` sekitar 80% batas memori container (sekitar 800 MiB di `mac-m2`) dan `GOGC` lebih tinggi (misalnya 200) | Menukar memori dengan GC yang lebih jarang |
| Go | Profile-guided optimization memakai profil dari run profiling (ADR-011) | Optimasi compiler berbasis profil beban nyata |
| Swift | Jumlah event loop 2 kali CPU, dibandingkan dengan 1 kali CPU | Menguji apakah event loop tambahan mengurangi antrean saat saturasi |
| Swift | Flag compiler tambahan yang didokumentasikan aman dan terbukti tersedia di Swift 6.4 | Optimasi build release tanpa mematikan pemeriksaan keamanan |

Sapuan ukuran pool koneksi (total 8, 16, 32, dan 64, sama untuk kedua stack) dijalankan pada S3 dan S8 di tahap A, untuk melihat titik saturasi terhadap ukuran pool.

Aturan:

- Semua perubahan dicatat di `tuning/variants.yaml`, maksimal tiga per stack. Setiap perubahan harus didukung versi terpasang (diverifikasi dari dokumentasi resmi atau perilaku runtime, bukan ditebak), dijelaskan alasannya, dan punya padanan di stack lain bila ada. Perubahan yang tidak bisa diverifikasi dibuang dan dicatat di Deviasi.
- Flag yang mematikan pemeriksaan keamanan (misalnya `-Ounchecked`) tidak dipakai.
- Varian dipilih lewat `VARIANT=default` atau `VARIANT=tuned`, dijalankan dari `docker-compose.tuned.yml` sebagai override, sehingga konfigurasi default tidak pernah berubah.
- Laporan menampilkan default dan tuned berdampingan beserta selisihnya. Kesimpulan utama hanya bersumber dari default.
- Target Makefile: `bench-tuned`.

## Profiling di run terpisah

Profiling dijalankan sebagai run khusus pada S8 dengan laju tetap 50% RPS saturasi, dengan aplikasi native di macOS, dan hasilnya hanya dipakai untuk menjelaskan selisih, bukan sebagai angka perbandingan. Keputusan ada di ADR-011.

| Stack | Alat | Keluaran |
| --- | --- | --- |
| Go | `net/http/pprof` di port admin 6060, aktif hanya bila `PROFILE=1`: profil CPU 45 detik, serta snapshot heap, alokasi, dan goroutine | File `.pb.gz` dan tampilan SVG |
| Swift | `sample <pid> 45` (bawaan macOS) untuk call tree teks, dan Instruments Time Profiler lewat `xctrace` bila Xcode terpasang | Teks hasil `sample` dan trace Instruments bila ada |

- Aplikasi dijalankan native (`go-run` dan `swift-run`, konfigurasi `release`). Postgres tetap di Docker lewat port yang dipublikasikan ke localhost, dan k6 di container menembak aplikasi lewat `host.docker.internal`.
- Keluaran di `results/profiles/<app>/<skenario>/`. Laporan memuat 10 fungsi teratas per stack dari data profil dan tautan ke file mentah.
- Profiler tidak pernah aktif saat run pengukuran. Laporan memberi label "penjelasan, bukan perbandingan" karena profil berasal dari proses native, bukan dari VM Docker.
- Laporan tidak menyimpulkan penyebab selisih secara otomatis. Narasi hanya ditulis bila didukung langsung oleh data profil.
- Target Makefile: `profile` dengan variabel `APP`, `SCENARIO`, dan `DURATION` (default 45 detik).

## Arsitektur kode: monorepo modular

Repo tetap satu monorepo, dan kedua aplikasi disusun modular dengan lapisan yang setara, supaya perbandingan DX dan skalabilitas basis kode tidak bias oleh struktur yang berbeda. Keputusan ada di ADR-014.

| Lapisan | Go | Swift |
| --- | --- | --- |
| Domain (model dan validasi) | `internal/domain` | target `Domain` |
| Penyimpanan (repositori ORM) | `internal/store` (GORM) | target `Persistence` (Fluent) |
| HTTP (route, handler, middleware) | `internal/httpapi` (chi) | target `HTTPAPI` (Vapor) |
| Platform (konfigurasi, logging, pool) | `internal/platform` | target `Platform` |
| Entry point | `cmd/server` | target executable `App` |

- Arah dependency satu arah: HTTP bergantung pada Store, Store bergantung pada Domain, dan Platform dipakai dari atas. Tidak ada dependency melingkar.
- Go memakai satu module (idiomatik) dan Swift memakai satu paket SwiftPM dengan banyak target. Perbandingan satu modul vs banyak modul dilakukan di eksperimen M1, bukan di aplikasi utama.
- Repositori ORM dan handler dipisah lewat antarmuka kecil, sehingga suite test paritas (DX2) bisa memakai repositori palsu tanpa database.
- Struktur lapisan yang sama dicek oleh `make contract`: daftar paket dan target harus cocok dengan tabel di atas.

## Developer Experience (DX1 sampai DX5)

DX dinilai dari lima pengukuran terstruktur, ditambah build time (B1 sampai B3) dan startup (S12), dengan pemisahan tegas antara yang terukur dan yang opini. Keputusan ada di ADR-013.

| ID | Metrik | Cara ukur | Sifat |
| --- | --- | --- | --- |
| DX1 | Edit sampai siap | Dari satu file diubah sampai `/healthz` merespons 200 pada proses native (build B2 konfigurasi dev ditambah start proses) | Kuantitatif |
| DX2 | Waktu test suite | Suite paritas dengan sedikitnya 20 kasus yang sama: validasi, JSON, dan handler dengan repositori palsu. `go test ./...` vs `swift test`, dalam kondisi cache kosong dan hangat | Kuantitatif |
| DX3 | Ukuran kode dan dependency | Baris kode non-kosong non-komentar, jumlah file, dependency langsung dan transitif, ukuran cache dependency | Kuantitatif, deskriptif |
| DX4 | Diagnostik compiler | Tiga mutasi baku: tipe tidak cocok, simbol tidak terdefinisi, error tidak ditangani. Keluaran compiler disimpan apa adanya, dengan jumlah baris dan apakah menunjuk lokasi yang benar | Kualitatif |
| DX5 | Onboarding | Dari clone bersih sampai request pertama sukses: jumlah perintah, jumlah prasyarat yang harus dipasang, dan waktu (B1 dev ditambah start native) | Campuran |

Aturan:

- Semua pengukuran DX berjalan native di macOS dengan cache terisolasi, memakai aturan yang sama dengan build time (ADR-008), dan tidak boleh berjalan bersamaan dengan beban Docker.
- Suite test paritas ditulis di kedua aplikasi dengan kasus yang sama dan daftar kasus yang sama (disimpan di `contract-tests/parity-cases`). Framework test Swift (Swift Testing atau XCTest) dipilih satu dan dicatat.
- DX4 memakai mutasi yang diterapkan lewat skrip pada salinan sementara kode, tidak pada kode utama. Keluaran compiler disimpan di `results/raw/dx/diagnostics/` dan tidak diubah menjadi skor.
- DX5 dihitung dari perintah dan prasyarat yang tercantum di `make doctor` dan README, bukan dari perkiraan.
- Target Makefile: `dx-bench`. Hasil ditulis ke `results/raw/dx/`.

## Skalabilitas (SC1 sampai SC3)

Skalabilitas dinilai lewat tiga lensa: seberapa efisien tiap stack menambah CPU, bagaimana resource tumbuh saat konkurensi naik, dan bagaimana biaya build membesar saat basis kode tumbuh, termasuk perbandingan satu modul vs banyak modul. Keputusan ada di ADR-014.

| Lensa | Skenario | Cara ukur | Keluaran |
| --- | --- | --- | --- |
| SC1 Skala vertikal | S14 (P1) | Batas CPU aplikasi 1, 2, dan 3 (`SCALE_CPUS`), dengan `GOMAXPROCS` dan jumlah event loop sama dengan CPU dan pool koneksi 8 kali CPU. S3 dan S8 tahap A | RPS vs CPU dan efisiensi skala: RPS(n) dibagi (n kali RPS(1)) |
| SC2 Skala konkurensi | Turunan tahap A | Dari data tangga konkurensi yang sudah ada | Kemiringan memori puncak per 100 koneksi virtual, pertumbuhan thread per koneksi, titik lutut latensi |
| SC3 Skala basis kode | M1 (P1) | Proyek sintetis dengan N modul, dua topologi, tiga jenis build | Kurva waktu build vs N per topologi dan kemiringannya |

### S14: skala vertikal

- Postgres tetap 2 CPU dan VM tetap 8 vCPU. Run ditandai "terbatas DB" bila CPU Postgres mencapai 90% atau lebih (dari sampler), karena di titik itu skala aplikasi tidak lagi terukur.
- Rentang kesimpulan dibatasi 1 sampai 3 core, dan laporan menyebutkannya.
- Target Makefile: `scale-bench`.

### M1: eksperimen skala basis kode (monorepo satu modul vs banyak modul)

- Generator (`tools/modgen`) membuat proyek sintetis di direktori sementara berakhiran `.noindex`, di luar kode aplikasi. N bernilai 1, 5, dan 20 secara default (50 opsional lewat `MODULES`). Tiap modul berisi model, validasi, dan handler sekitar 100 baris, bergantung hanya pada modul inti, dan memakai dependency yang sama dengan aplikasi (chi dan `encoding/json` untuk Go, Vapor dan Codable untuk Swift) dengan dependency sudah ter-cache.
- Dua topologi per stack. T1: satu module atau paket (Go: satu module dengan N package, Swift: satu paket dengan N target). T2: banyak module atau paket (Go: N module dalam `go.work`, Swift: N paket lokal yang direferensikan lewat path).
- Tiga jenis build: B3 (dependency ter-cache, artefak dibuang), B2-leaf (ubah satu modul daun), dan B2-core (ubah modul inti yang dipakai semua modul). Native macOS, cache terisolasi, konfigurasi dev, ulangan sesuai `BUILD_REPEATS`.
- Kode sintetis bukan kode produksi, jadi laporan memberi label bahwa kurva menunjukkan biaya struktur, bukan kualitas arsitektur.
- Target Makefile: `modular-bench`. Hasil ke `results/raw/modular/`, dan orkestrator mencetak estimasi durasi sebelum mulai.

## Kesimpulan DX dan skalabilitas di laporan

Laporan menutup dengan bagian Kesimpulan yang disusun dari data oleh `tools/report`, dengan aturan ketat supaya kesimpulan tidak berubah menjadi selera: setiap kalimat menunjuk ke metrik, dan hanya selisih yang melampaui variasi yang disebut sebagai selisih.

Struktur bagian Kesimpulan:

1. **Ringkasan** satu paragraf untuk DX dan satu untuk skalabilitas, memuat hanya temuan yang lolos aturan di bawah.
2. **Matriks kriteria** dengan kolom kriteria, median Go, median Swift, rentang, dan hasil (lebih baik atau setara). Barisnya: B1, B2, B3 (dev dan release), DX1, DX2, DX3, DX5, waktu start dan ukuran image (S12), efisiensi skala S14, kemiringan memori SC2, dan kemiringan waktu build M1 per topologi.
3. **Rekomendasi arsitektur kondisional** untuk monorepo satu modul vs banyak modul, per stack, dari data M1.
4. **Tidak diukur**: faktor yang relevan tetapi tidak terukur (kematangan ekosistem dan library, dukungan IDE dan debugging, ketersediaan engineer, stabilitas rilis seperti transisi Vapor 4 ke 5). Faktor ini ditulis dengan sumber atau diberi label "dari pengetahuan umum", tanpa bobot, dan tidak dicampur ke dalam kesimpulan terukur.
5. **Batas kesimpulan**: hasil berlaku untuk MacBook M2 Pro, versi yang dikunci, kode sintetis (M1), dan rentang 1 sampai 3 core (S14).

Aturan penyusunan:

- Stack dinyatakan lebih baik pada sebuah metrik hanya bila rentang minimum sampai maksimum kedua stack tidak tumpang tindih dan selisih median lebih dari 5%. Selain itu hasilnya "setara" atau "belum cukup bukti".
- Kalimat kesimpulan memakai bentuk baku, misalnya "Pada B2-leaf di topologi T1 dengan 20 modul, stack X membangun Y% lebih cepat (median, rentang tidak tumpang tindih)", dengan angka dari tabel yang ditautkan.
- Rekomendasi monorepo atau modular hanya mencakup rentang N yang diuji dan harus memuat kondisinya, misalnya "pada N modul ke atas, T2 mengurangi waktu B2-leaf". Tanpa data yang lolos aturan, bagian itu menulis "belum ada rekomendasi yang didukung data".
- DX4 (kualitatif) hanya menampilkan contoh keluaran dan observasi faktual, tanpa skor dan tanpa pemenang.
- Dilarang menyimpulkan penyebab selisih tanpa dukungan profil (ADR-011) atau dokumentasi yang dikutip.

## Metrik dan pengumpulan data

Setiap run menghasilkan time-series resource per detik dan ringkasan throughput serta latensi, lalu diagregasi dari beberapa ulangan menjadi median, minimum, maksimum, dan koefisien variasi.

| Kategori | Metrik | Sumber |
| --- | --- | --- |
| Throughput dan latensi | RPS, p50, p90, p95, p99, p99.9, maksimum, error rate, histogram status code, dropped iterations (mode open-loop) | Ringkasan JSON k6 per titik ukur |
| CPU | Total CPU dalam core terpakai, pemisahan user vs system, jumlah dan durasi throttling | cgroup v2 `cpu.stat` tiap 1 detik, dibaca container sampler |
| Memori | Idle setelah startup, rata-rata, puncak, laju pertumbuhan (MB per menit), nilai akhir setelah beban reda, rincian anon vs file | cgroup v2 `memory.current`, `memory.peak`, `memory.stat` |
| Proses | Jumlah thread, file descriptor, context switch sukarela dan tidak sukarela | `pids.current`, `/proc/<pid>/status`, `/proc/<pid>/fd` |
| Jaringan dan disk | Byte masuk dan keluar, I/O blok | `/proc/<pid>/net/dev`, cgroup `io.stat`, `docker stats` sebagai pembanding silang |
| Runtime Go | Jumlah goroutine, siklus GC, total jeda GC, heap alloc | `runtime/metrics` lewat port admin terpisah (6060) |
| Postgres | Jumlah query per request, waktu eksekusi rata-rata per query, koneksi aktif dan idle, wait event | `pg_stat_statements`, `pg_stat_database`, `pg_stat_activity` (snapshot sebelum dan sesudah run) |
| Logging | Jumlah baris dan byte log per request, selisih CPU dan latensi antara mode `quiet` dan `access` (S11) | Hitungan baris log container dan perbandingan run S11 |
| Statik | Ukuran image dan binary, waktu start sampai `/healthz` sukses (S12) | `docker image inspect` dan `startup-bench` |
| Lingkungan Mac | Model Mac, versi macOS, ukuran VM Docker, status thermal sebelum dan sesudah run | `sysctl`, `sw_vers`, `docker info`, `pmset -g therm` |
| Build time | Wall time, CPU user dan system, peak RSS, ukuran binary, dan paralelisme efektif untuk B1, B2, B3 pada konfigurasi dev dan release | /usr/bin/time -l lewat tools/buildtime, native macOS |
| Startup dan cold start | Waktu start sampai siap, latensi request pertama per endpoint, memori idle | startup-bench (S12) |
| Profil | Profil CPU, heap, dan alokasi (Go), call tree (Swift), 10 fungsi teratas per stack | profile, run terpisah, native macOS |
| Developer Experience | DX1 edit sampai siap, DX2 waktu test suite (cold dan warm), DX3 baris kode dan jumlah dependency, DX4 keluaran compiler (kualitatif), DX5 langkah dan waktu onboarding | dx-bench, native macOS, hasil di results/raw/dx/ |
| Skalabilitas | Efisiensi skala vertikal (S14), kemiringan memori dan thread per koneksi (SC2), kurva waktu build vs jumlah modul pada topologi T1 dan T2 (M1) | scale-bench, modular-bench, dan turunan dari tahap A |

Bila sampler tidak bisa membaca cgroup di Docker Desktop, ia turun ke `docker stats` dengan fidelitas lebih rendah (tanpa pemisahan user vs system dan tanpa throttling), dan laporan menandai hal itu.

### Metrik turunan (angka utama di laporan)

- CPU-ms per request dan RPS per core CPU terpakai.
- RPS per GB memori puncak.
- Latensi p99 dan memori pada laju tetap yang sama (tahap B), karena membandingkan resource pada throughput berbeda menyesatkan.
- Biaya logging per stack: selisih CPU-ms per request dan p99 antara `quiet` dan `access`.
- Jumlah query per request per implementasi, untuk mendeteksi N+1 atau perbedaan perilaku ORM.
- Rasio Swift terhadap Go dengan rentang dari ulangan. Run dengan CV di atas 5% diberi tanda dan tidak dipakai untuk kesimpulan tanpa diulang.

### Format keluaran

Setiap run menyimpan `results/raw/<run-id>/` berisi CSV time-series resource, ringkasan k6, snapshot Postgres, dan metadata lingkungan. Folder `results/` berisi agregat CSV, `report.md`, dan grafik PNG (kurva RPS vs konkurensi, latensi vs laju, CPU dan memori vs waktu).

## Aturan kesetaraan

Perbandingan dianggap adil hanya jika semua variabel di luar bahasa dan framework dikunci sama, dan setiap pengecualian dicatat di laporan.

| Aspek | Aturan | Go | Swift |
| --- | --- | --- | --- |
| CPU dan memori container | Batas sama persis | `GOMAXPROCS` diset eksplisit sama dengan batas CPU | Jumlah event loop diset eksplisit sama dengan batas CPU |
| Koneksi database total | 8 kali CPU aplikasi (16 di `mac-m2`) | `SetMaxOpenConns` dan `SetMaxIdleConns` sama dengan total | `maxConnectionsPerEventLoop` dihitung dari total dibagi jumlah event loop |
| Protokol query | Extended protocol dengan prepared statement di kedua sisi | GORM `PrepareStmt: true` | Default PostgresNIO, diverifikasi lewat `pg_stat_statements` |
| Akses data | Hanya lewat ORM, tanpa SQL mentah di kode aplikasi | `First`, `Preload`, `Create`, `Updates` | `find`, `with`, `create`, `update` |
| Skema dan data | Dibuat hanya oleh `db/schema.sql` dan seed yang sama, tanpa auto-migrate | Tabel dipetakan eksplisit | Tabel dipetakan eksplisit, tanpa migrasi Fluent |
| JSON | Library idiomatik bawaan | `encoding/json` Go 1.27 | Foundation `JSONEncoder` dan `JSONDecoder` lewat Vapor Content |
| HTTP | HTTP/1.1 keep-alive, tanpa TLS dan kompresi | Server chi di `net/http` | Server Vapor 4 |
| Logging | Mode, level, dan tujuan keluaran sama. Format teks di kedua sisi | LogLayer + slog, handler teks, `loghttp` | SwiftLog bawaan, `RouteLoggingMiddleware` pada mode `access` |
| Beban | k6 v2 yang sama, skrip sama, PRNG ber-seed sama | sama | sama |
| Build | Release dan runtime image kecil, arm64 | `CGO_ENABLED=0`, `-trimpath`, `-ldflags="-s -w"` | `swift build -c release --static-swift-stdlib`, runtime pada image slim |
| Tuning runtime | Default, tanpa tuning sepihak | `GOGC` default, tanpa `GOMEMLIMIT` | Tanpa flag tambahan |
| Postgres | Satu konfigurasi untuk keduanya | `shared_buffers` 512 MB, `max_connections`, dan `synchronous_commit=off` sama (fsync tetap aktif) | sama |
| Urutan dan keadaan awal | Satu aplikasi aktif, DB direset, urutan diacak | sama | sama |
| Base image runtime | Distroless atau Alpine, non-root, tahap build bebas, flavor sama untuk kedua stack | distroless static (binary statis tanpa libc) | distroless cc (glibc), fallback Alpine musl dengan label |
| Arsitektur kode | Lapisan setara dan satu arah: domain, penyimpanan, HTTP, platform | internal/domain, store, httpapi, platform | target Domain, Persistence, HTTPAPI, Platform |

Gerbang kesetaraan otomatis sebelum benchmark berjalan (gagal berarti benchmark berhenti):

1. **Uji kontrak:** setiap endpoint di kedua aplikasi mengembalikan status dan bentuk JSON yang sama dengan golden JSON dari fixture, termasuk kasus 400 dan 404.
2. **Uji jumlah query:** setiap endpoint menghasilkan jumlah query yang sama per request di kedua aplikasi, diukur dari `pg_stat_statements`.
3. **Uji konfigurasi dan logging:** nilai pool, thread, dan batas container yang terbaca saat runtime sama dengan rencana. Mode `quiet` tidak menulis baris akses, dan mode `access` menulis tepat satu baris akses per request di kedua aplikasi.
4. **Uji data:** checksum tabel setelah seed sama dengan nilai acuan di repo.

Tuning tambahan (misalnya `GOMEMLIMIT`, ukuran pool berbeda, atau format log JSON) hanya boleh dijalankan sebagai varian terpisah yang diberi label, dan diterapkan pada kedua sisi bila ada padanannya.

## Deliverables dan struktur repo

Hasil akhirnya satu repo yang bisa dijalankan lewat `make`, berisi kedua aplikasi, infrastruktur uji, skrip analisis, dan laporan.

```text
bench-go-vs-swift/
  README.md                 cara menjalankan, syarat Mac, cara membaca hasil, Asumsi dan Deviasi
  docs/PRD.md               salinan PRD ini
  docs/ADR.md               salinan ADR
  Makefile                  satu pintu masuk (kompatibel GNU Make 3.81 bawaan macOS)
  .env.example              profil resource, ambang SLO, ulangan, mode log, varian, flavor image
  docker-compose.yml        postgres, go-app, swift-app, k6, sampler, probe, profil monitoring
  docker-compose.tuned.yml  override untuk varian tuned
  db/                       schema.sql, seed.sql, postgres.conf, fixtures/, checksums.txt
  go-app/                   go.mod, cmd/server, internal/{domain,store,httpapi,platform}, Dockerfile, Dockerfile.alpine
  swift-app/                Package.swift, Sources/{Domain,Persistence,HTTPAPI,Platform,App}, Dockerfile, Dockerfile.alpine
  contract-tests/           kasus uji kontrak, golden JSON, uji jumlah query dan logging, parity-cases/
  loadtest/                 skrip k6 per skenario, util PRNG ber-seed, data/ (hasil seed)
  tuning/                   variants.yaml (perubahan tuned, alasan, bukti verifikasi)
  tools/                    sampler, orkestrator, buildtime, startup, profiler, dx, modgen, agregator, pembuat laporan
  results/                  raw/ (beban, build, startup, dx, modular), profiles/, dan agregat (di-gitignore, kecuali contoh)
```

### Target Makefile

Detail keputusan ada di ADR-007 dan pembaruannya. `make help` menampilkan daftar ini dengan deskripsi satu baris.

| Kelompok | Target | Fungsi |
| --- | --- | --- |
| Bantuan | `help`, `doctor` | Daftar target. `doctor` mengecek arsitektur arm64, versi Docker, ukuran VM Docker, akses sampler ke cgroup, toolchain native (Go 1.27.2 dan Swift 6.4), charger, dan status thermal |
| Database | `db-up`, `db-down`, `db-seed`, `db-reset`, `db-psql` | Jalankan Postgres, seed dan checksum, reset dari template, buka `psql` |
| Go | `go-build`, `go-run`, `go-test`, `go-image`, `go-up`, `go-down`, `go-logs` | `go-build` dan `go-run` native di Mac (butuh Postgres dari `db-up`). `go-image` dan `go-up` memakai container dengan batas resource profil |
| Swift | `swift-build`, `swift-run`, `swift-test`, `swift-image`, `swift-up`, `swift-down`, `swift-logs` | Sama seperti Go. Bila toolchain Swift 6.4 belum ada di Mac, target native memakai container |
| Verifikasi | `contract` | Uji kontrak, jumlah query, logging, konfigurasi, dan checksum untuk kedua aplikasi |
| Benchmark beban | `bench-smoke`, `bench-core`, `bench`, `bench-tuned`, `startup-bench` | Smoke cepat, skenario inti (S1, S3, S4, S8), semua skenario, varian tuned (S13), dan startup (S12) |
| Build time | `build-bench`, `build-bench-clean`, `build-bench-incr`, `build-bench-cached` | Semua skenario build, atau B1, B2, B3 saja. Native macOS, cache terisolasi |
| Profiling | `profile` | Profil CPU dan alokasi di run terpisah, aplikasi native |
| Laporan | `report` | Bangun `report.md`, CSV agregat, dan grafik dari `results/` |
| Bersih | `clean`, `clean-all` | Hapus hasil dan artefak, atau hapus juga image dan volume |
| Developer Experience | dx-bench | DX1 sampai DX5: edit sampai siap, waktu test suite paritas, baris kode dan dependency, mutasi diagnostik compiler, onboarding. Native macOS |
| Skalabilitas | scale-bench, modular-bench | scale-bench menjalankan S14 (CPU 1, 2, 3). modular-bench menjalankan M1 (proyek sintetis N modul, topologi T1 dan T2) |

Variabel yang bisa diubah di baris perintah:

- `APP` bernilai go, swift, atau both (default both).
- `SCENARIO` berisi daftar seperti s1,s3,s8, atau core, atau all.
- `REPEATS` (default 3), `PROFILE` (default mac-m2), `SLO_P99_MS` (default 250).
- `LOG_MODE` bernilai quiet atau access, dan `LOG_FORMAT` bernilai text atau json (hanya Go).
- `VARIANT` bernilai default atau tuned.
- `IMAGE_FLAVOR` bernilai distroless (default) atau alpine.
- `BUILD_REPEATS` (default B1 sebanyak 3, B2 sebanyak 5, B3 sebanyak 3) dan `BUILD_CONFIG` bernilai dev, release, atau both.
- `SCALE_CPUS` (default 1,2,3) untuk S14, dan `MODULES` (default 1,5,20; 50 opsional) untuk M1.
- `DURATION` untuk profiling (default 45 detik).

Contoh pemakaian: `make doctor`, lalu `make db-up db-seed`, `make go-run` atau `make swift-run` untuk pengembangan, `make contract`, `make bench APP=both SCENARIO=core` untuk benchmark beban, `make build-bench` untuk build time, dan `make profile APP=go SCENARIO=s8` untuk profiling. Eksekusi native hanya untuk pengembangan, build time, dan profiling. Benchmark beban selalu memakai container dan dibungkus `caffeinate`.

Laporan akhir (`results/report.md`) memuat: ringkasan eksekutif, tabel RPS dan latensi per skenario, tabel resource usage pada laju tetap, biaya logging, tabel build time (B1 sampai B3, dev dan release), ukuran image dan startup (kedua flavor bila ada), perbandingan default vs tuned, hasil DX1 sampai DX5, hasil skalabilitas (S14, SC2, M1), 10 fungsi teratas dari profil, grafik, versi dan konfigurasi lengkap, checksum seed, daftar peringatan validitas, batasan interpretasi, dan bagian Kesimpulan DX dan skalabilitas dengan aturan penyusunan di PRD.

## Kriteria penerimaan

Pekerjaan dianggap selesai bila semua butir berikut terpenuhi dan dibuktikan lewat keluaran perintah, bukan klaim.

- [ ] `make doctor` lulus di MacBook M2 Pro: arsitektur arm64, VM Docker sedikitnya 8 vCPU dan 8 GB, semua image linux/arm64, dan sampler bisa membaca cgroup (atau turun ke `docker stats` dengan penanda).
- [ ] `make help` menampilkan semua target pada tabel Makefile, tiap target punya deskripsi satu baris, dan Makefile berjalan di GNU Make 3.81 bawaan macOS.
- [ ] `make go-build`, `make go-run`, `make swift-build`, dan `make swift-run` membuat dan menjalankan masing-masing aplikasi, dan `GET /healthz` merespons. Bila toolchain Swift 6.4 tidak ada di Mac, target Swift native memakai container dan README mencatatnya.
- [ ] `make go-up` dan `make swift-up` menjalankan aplikasi dalam container dengan batas resource profil `mac-m2`.
- [ ] `make contract` lulus: semua endpoint identik di kedua aplikasi terhadap golden JSON, jumlah query per request sama, mode log `quiet` tanpa baris akses dan `access` dengan satu baris per request, dan checksum seed cocok.
- [ ] Log Go lewat LogLayer + slog (`loghttp` di chi) dan log Vapor lewat SwiftLog bawaan terbukti menulis ke stdout pada kedua mode.
- [ ] `make bench-smoke` selesai di bawah 15 menit dan menghasilkan `report.md` berisi semua skenario P0.
- [ ] Sampler menghasilkan CSV per detik untuk CPU (user dan system), memori, thread, dan FD pada setiap run.
- [ ] Tahap A menghasilkan kurva RPS vs konkurensi dan titik saturasi untuk S1 sampai S8 di kedua stack, dan tahap B menghasilkan latensi dan resource usage pada laju tetap yang sama.
- [ ] S11 menghasilkan biaya logging per stack (selisih `quiet` dan `access`).
- [ ] Setiap titik ukur punya ulangan sesuai `REPEATS` dengan median dan CV, dan run dengan CV di atas 5%, CPU k6 di atas 80%, atau throttling thermal ditandai.
- [ ] README menjelaskan syarat Mac, cara menjalankan, cara membaca hasil, Asumsi, Deviasi, dan batasan interpretasi.
- [ ] Semua versi dependensi terkunci (`go.sum`, `Package.resolved`, versi image k6, digest image).

### Tambahan versi 3: build time, startup, varian tuned, dan profiling

- [ ] `make build-bench-clean`, `make build-bench-incr`, dan `make build-bench-cached` berjalan native untuk kedua stack pada konfigurasi dev dan release, memakai cache terisolasi dan tanpa menyentuh cache global pengguna.
- [ ] Hasil build time memuat wall time, CPU user dan system, peak RSS, ukuran binary, dan paralelisme efektif, dengan median, rentang, dan CV. B1 menampilkan rincian unduh dependency vs kompilasi.
- [ ] Setelah B2, hash binary berubah (bukti kompilasi ulang), dan compilation caching SwiftPM terverifikasi tidak aktif.
- [ ] `make doctor` menolak `build-bench` dan `profile` dengan petunjuk jelas bila Go 1.27.2 atau toolchain Swift 6.4 native tidak ada.
- [ ] `make startup-bench` menghasilkan ukuran image dan binary, waktu start sampai `/healthz`, latensi request pertama per endpoint, dan memori idle, dengan 10 ulangan per stack.
- [ ] `tuning/variants.yaml` memuat maksimal tiga perubahan per stack, tiap perubahan dengan alasan dan bukti verifikasi, dan `make bench-tuned` menghasilkan perbandingan default vs tuned serta sapuan ukuran pool tanpa mengubah konfigurasi default.
- [ ] `make profile` menghasilkan profil Go (CPU, heap, alokasi) dan profil Swift (`sample`) untuk S8 pada 50% saturasi, 10 fungsi teratas per stack di laporan, dan label "penjelasan, bukan perbandingan".

### Tambahan versi 4: base image, DX, dan skalabilitas

- [ ] Image runtime kedua aplikasi adalah Distroless atau Alpine, berjalan sebagai non-root, dan `docker image inspect` serta hasil menjalankan binary membuktikannya. Bila Swift jatuh ke Alpine musl, laporan memberi label musl.
- [ ] `make bench IMAGE_FLAVOR=alpine` berjalan untuk flavor Alpine, dan S12 melaporkan ukuran dan startup untuk kedua flavor bila keduanya berhasil dibangun.
- [ ] Struktur kode kedua aplikasi mengikuti lapisan setara (domain, penyimpanan, HTTP, platform, entry point) dengan dependency satu arah, dan `make contract` memeriksa daftar paket dan target.
- [ ] Suite test paritas (sedikitnya 20 kasus yang sama) lulus di kedua aplikasi, dan `make dx-bench` melaporkan DX1 sampai DX5 dengan median, rentang, dan CV, serta keluaran compiler DX4 disimpan apa adanya.
- [ ] `make scale-bench` melaporkan RPS dan efisiensi skala pada 1, 2, dan 3 CPU, dan menandai run yang terbatas DB.
- [ ] `make modular-bench` menghasilkan kurva B3, B2-leaf, dan B2-core terhadap N modul untuk topologi T1 dan T2 di kedua stack, tanpa menyentuh kode aplikasi utama.
- [ ] Bagian Kesimpulan di `report.md` mengikuti aturan penyusunan: setiap klaim menunjuk metrik, selisih hanya disebut bila rentang tidak tumpang tindih dan median berbeda lebih dari 5%, faktor tidak terukur dipisah, dan rekomendasi monorepo atau modular hanya mencakup rentang N yang diuji.

## Risiko dan batasan interpretasi

Risiko terbesar adalah angka yang tampak presisi tetapi dipengaruhi laptop, VM Docker, load generator, atau kode yang tidak setara, sehingga setiap risiko di bawah punya pengaman otomatis atau label di laporan.

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Laptop dan VM Docker: noise, core performance vs efficiency, throttling thermal | Angka bising dan tidak sebanding dengan server | Hasil dibaca relatif, `caffeinate`, charger, catat `pmset -g therm`, ulangan dan penanda CV di atas 5%, tandai run yang terkena throttling |
| Memori 16 GB dibagi dengan macOS | VM Docker kekurangan memori dan swap | VM dibatasi 8 GB, total batas container sekitar 4 GB, `make doctor` memeriksa ukuran VM |
| k6 berebut CPU dengan aplikasi di VM yang sama | RPS terukur adalah batas k6, bukan aplikasi | `cpuset` terpisah, batas CPU k6 80%, validasi silang S1 dengan alat lain bila perlu |
| Sampler tidak bisa membaca cgroup di Docker Desktop | Pemisahan CPU user vs system hilang | Verifikasi di `make doctor`, fallback ke `docker stats` dengan penanda di laporan |
| Kode dua aplikasi tidak setara | Perbandingan bias | Gerbang kontrak, jumlah query, logging, dan checksum sebelum benchmark |
| Perilaku ORM berbeda (bentuk SQL, eager loading) | Selisih berasal dari ORM, bukan bahasa | Catat SQL aktual dari `pg_stat_statements` dan jelaskan di laporan |
| Lapisan logging berbeda (LogLayer + slog vs SwiftLog) dan format log berbeda | Biaya logging tidak persis sebanding | Format teks di kedua sisi, mode `quiet` sebagai baseline, S11 memisahkan biaya, dan perbedaan dinyatakan di laporan |
| `synchronous_commit=off` | Biaya tulis lebih rendah dari produksi | Dinyatakan di laporan. Varian `synchronous_commit=on` tidak termasuk lingkup versi ini |
| Dataset muat di memori | Tidak mewakili beban yang terikat disk | Dinyatakan sebagai batasan |
| Vapor 5 masih beta | Hasil varian V5 bisa berubah | Hanya varian opsional dengan label eksperimental |
| Tag image atau versi belum terverifikasi | Build gagal atau versi berbeda dari yang diminta | Langkah verifikasi di awal dan catatan deviasi di README |
| Toolchain Swift 6.4 native belum ada di Mac | `swift-run` native tidak jalan | Fallback ke container, benchmark tidak terpengaruh karena selalu memakai container |

Batasan interpretasi yang wajib tertulis di laporan:

- Hasil berlaku untuk MacBook M2 Pro dengan Docker Desktop VM, profil resource, versi, dan beban yang diuji, bukan klaim umum tentang bahasa atau server.
- Perbedaan kecil (di bawah variasi antar ulangan) tidak boleh dibaca sebagai selisih nyata.
- Resource usage hanya sebanding pada laju tetap yang sama (tahap B). Perbandingan pada saturasi menunjukkan kapasitas, bukan efisiensi.

### Risiko tambahan (versi 3)

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Build time native terpengaruh proses latar macOS, Spotlight, dan penjadwalan core performance vs efficiency | Waktu build bising | Cache di direktori `.noindex`, aplikasi lain ditutup, jeda thermal, urutan Go dan Swift diselang-seling, ulangan dengan median dan CV |
| Unduhan dependency di B1 bergantung jaringan | B1 tidak bisa dibandingkan antar sesi | Rincian unduh vs kompilasi dilaporkan terpisah, dan perbandingan utama memakai bagian kompilasi |
| Cache tersembunyi (compilation caching SwiftPM atau cache global) | B1 dan B3 terlalu cepat | Cache terisolasi, verifikasi compilation caching nonaktif, dan bukti hash binary berubah di B2 |
| Toolchain Go atau Swift native tidak terpasang di Mac | Build time dan profiling tidak bisa dijalankan | `make doctor` menolak dengan petunjuk, tanpa pemasangan otomatis |
| Opsi SwiftPM atau flag `--static-swift-stdlib` berbeda perilaku di macOS | Skenario build gagal atau tidak setara | Agen memverifikasi opsi di toolchain terpasang dan mencatat penyimpangan di Deviasi |
| Profil berasal dari proses native, bukan dari VM Docker | Profil tidak sebanding dengan angka beban | Label "penjelasan, bukan perbandingan" dan tanpa kesimpulan kausal otomatis |
| Tuning tidak setara antar stack | Varian tuned bias | Maksimal tiga perubahan per stack, tiap perubahan diverifikasi dan punya padanan bila ada, kesimpulan utama hanya dari default |
| Startup mencakup overhead Docker | Selisih absolut menyesatkan | Overhead sama untuk kedua stack, laporan membandingkan selisih dan menyebut komponennya |
| Distroless tidak punya shell, dan Swift mungkin tidak cocok dengan Distroless glibc | Health check dan debugging lebih sulit, atau image Swift gagal berjalan | Probe dari luar container, verifikasi dengan menjalankan binary, fallback Alpine musl dengan label dan penjelasan risiko alokator |
| Kode sintetis M1 tidak mewakili kode produksi | Rekomendasi monorepo atau modular terlalu percaya diri | Label sintetis di laporan, rekomendasi hanya untuk rentang N yang diuji, dan kondisional |
| VM 8 vCPU membatasi skala vertikal dan Postgres 2 CPU bisa menjadi bottleneck di S14 | Efisiensi skala tampak buruk karena DB, bukan aplikasi | Tandai run terbatas DB (CPU Postgres 90% atau lebih), batasi kesimpulan pada 1 sampai 3 core |
| DX sebagian subjektif | Kesimpulan DX menjadi selera | Hanya metrik terukur yang menentukan pemenang, DX4 kualitatif tanpa skor, dan faktor tidak terukur dipisah dengan sumber |
| Suite test paritas tidak benar-benar setara antar stack | DX2 membandingkan hal yang berbeda | Daftar kasus bersama di contract-tests/parity-cases dan pemeriksaan jumlah kasus yang sama di kedua suite |

## Lampiran: prompt satu kali hit untuk Claude Code (versi 4)

Jalankan `mkdir bench-go-vs-swift && cd bench-go-vs-swift && claude`, lalu tempel prompt di bawah. Prompt berdiri sendiri. Bila PRD dan ADR ikut disimpan ke `docs/`, keduanya menjadi sumber kebenaran.

```text
PERAN DAN CARA KERJA
Kamu Claude Code yang bekerja di direktori kosong bench-go-vs-swift/ pada MacBook Pro M2 Pro (macOS, arm64, RAM 16 GB, Docker Desktop). Kerjakan end-to-end dalam satu sesi tanpa bertanya balik. Hal ambigu: ambil asumsi paling masuk akal dan catat di README bagian 'Asumsi'. Penyimpangan dari spesifikasi ini: catat di README bagian 'Deviasi'. Gunakan daftar tugas internal, jalankan git init, dan commit di akhir tiap tahap. Verifikasi dengan perintah sungguhan dan baca keluarannya; jangan klaim berhasil tanpa bukti. Jika PRD dan ADR disertakan, simpan sebagai docs/PRD.md dan docs/ADR.md, dan anggap keduanya menang bila ada konflik.

TUJUAN
Bangun repo yang membandingkan dua backend API CRUD identik di atas satu Postgres (Docker Compose), diukur dengan k6:
(A) Go 1.27.2 + chi v5 + GORM (gorm.io/driver/postgres) + LogLayer v3 dengan transport log/slog
(B) Swift 6.4.0 + Vapor 4 (stabil, rilis 4.x terbaru) + Fluent 4 + fluent-postgres-driver + logging bawaan Vapor (SwiftLog)
Ukur RPS, latensi, resource usage rinci (CPU user vs system, memori, thread, FD, network, I/O), biaya logging, build time native macOS (B1, B2, B3), ukuran image dan startup (S12), varian tuned (S13), profiling terpisah, Developer Experience (DX1 sampai DX5), dan skalabilitas (S14, SC2, M1: monorepo satu modul vs banyak modul), lalu susun kesimpulan DX dan skalabilitas dari data. Semua dijalankan lewat Makefile dan image runtime memakai Distroless atau Alpine. Vapor 5 masih beta (butuh Swift 6.4, WebSocket dan kompresi belum ada): jangan dipakai di stack utama.

LANGKAH 0 - VERIFIKASI SEBELUM MENULIS KODE
1. Lingkungan: uname -m harus arm64; sw_vers; sysctl hw.model hw.ncpu hw.memsize hw.perflevel0.physicalcpu hw.perflevel1.physicalcpu; docker info (jumlah CPU, memori, versi cgroup); make --version (macOS membawa GNU Make 3.81: Makefile TIDAK boleh memakai .ONESHELL, grouped targets, atau fungsi yang baru ada di Make 4).
2. VM Docker butuh sedikitnya 8 vCPU dan 8 GB. Jika kurang, make doctor gagal dengan petunjuk mengubah Docker Desktop Settings > Resources. Jangan mengubah pengaturan itu sendiri.
3. Toolchain native (untuk build-bench dan profile): go version harus 1.27.2 (atau catat deviasi), swift --version harus 6.4 (Xcode 27 atau toolchain swift.org), xcode-select -p, dan keberadaan xcrun xctrace. Jika tidak ada, JANGAN memasang otomatis: make doctor menolak build-bench dan profile dengan petunjuk jelas, dan bagian lain tetap dibangun.
4. Verifikasi tag dan versi: golang:1.27.2 (jika tidak ada, pakai 1.27.x terbaru dan catat go version); image Swift 6.4 untuk build (pola swift:6.4-noble) dan image runtime Distroless atau Alpine sesuai bagian BASE IMAGE; Postgres stabil terbaru (kunci dengan digest); grafana/k6 seri 2.x (kunci versi persis); chi v5.3.x; gorm.io/gorm v1.31.x; gorm.io/driver/postgres v1.6.x; go.loglayer.dev/v3 beserta go.loglayer.dev/transports/slog/v3 dan go.loglayer.dev/integrations/loghttp/v3; Vapor 4.x, Fluent 4.x, fluent-postgres-driver 2.x terbaru yang kompatibel dengan Swift 6.4. Semua image harus linux/arm64 native, tanpa emulasi amd64.
5. Verifikasi khusus build: opsi SwiftPM --scratch-path, --cache-path, --config-path, --security-path diterima oleh swift build dan swift package resolve di Swift 6.4; apakah --static-swift-stdlib didukung di macOS (build Linux di image tetap memakainya); compilation caching SwiftPM tidak aktif secara default; GOCACHE dan GOMODCACHE terisolasi bekerja.
6. Verifikasi sampler: container dengan pid: host dan cgroup: host harus bisa membaca cgroup container lain di VM Docker Desktop. Temukan pola jalur cgroup dari ID container. Jika gagal, fallback ke docker stats dan tandai di laporan.
7. Verifikasi base image: tag Distroless static dan cc (arm64, nonroot) dan Alpine ada; jalankan binary Go dan Swift di image runtime kandidat (docker run) untuk membuktikan kecocokan library; bila Swift gagal di Distroless glibc, siapkan jalur Alpine dengan Static Linux SDK (musl) dan beri tanda.
8. Catat hasil verifikasi di README bagian 'Lingkungan terverifikasi'. Jika ada yang gagal, pilih alternatif terdekat dan catat di 'Deviasi'.

SKEMA DAN SEED (db/)
Skema hanya dibuat oleh db/schema.sql. Aplikasi TIDAK boleh membuat tabel atau auto-migrate (GORM AutoMigrate dan migrasi Fluent dilarang); model memetakan nama tabel dan kolom secara eksplisit.
users(id bigserial PK, name text, email text unique, created_at timestamptz) - 10.000 baris
orders(id bigserial PK, user_id bigint FK users, status text, total_cents int, note text, created_at timestamptz, updated_at timestamptz) - 500.000 baris
payments(id bigserial PK, order_id bigint FK orders, amount_cents int, created_at timestamptz) - kosong
Indeks: orders(user_id, created_at DESC) dan orders(status, id).
Seed benchmark (db/seed.sql) deterministik: generate_series dan fungsi hash (tanpa random() tak ber-seed). user_id order = 1 + floor(10000 * u^1.2) dengan u dari hash deterministik, status 20% pending / 50% paid / 20% shipped / 10% cancelled, created_at tersebar 365 hari dari tanggal tetap, total_cents 500..500000, note teks pendek deterministik. Ekspor loadtest/data/user_ids.json, order_ids.json, pending_order_ids.json. Cetak checksum per tabel (hash seluruh baris terurut) ke db/checksums.txt dan bandingkan pada tiap seed. Jalankan VACUUM ANALYZE, lalu simpan database hasil seed sebagai template (CREATE DATABASE ... TEMPLATE) untuk reset cepat antar run.
Fixture kecil (db/fixtures/): 20 user dan 100 order bernilai tetap tulisan tangan, termasuk user tanpa order, semua status, note kosong, dan note 200 karakter. Dipakai uji kontrak dengan golden JSON yang disimpan di repo.
Postgres identik untuk kedua aplikasi: pg_stat_statements aktif, shared_buffers 512MB, max_connections cukup, synchronous_commit=off (fsync tetap on), data di named volume (bukan bind mount).

KONTRAK ENDPOINT (identik di kedua aplikasi; JSON snake_case, timestamp RFC 3339 UTC, uang dalam sen)
GET /healthz -> {status: ok}
GET /bench/json -> objek tetap sekitar 1 KB (20 field + satu array kecil) dibuat di memori
POST /bench/echo -> decode body JSON bersarang sekitar 1 KB, validasi, encode ulang
GET /users/{id} -> satu user (1 query PK); 404 bila tidak ada
GET /users/{id}/orders?limit=20 -> 20 order terbaru, urut created_at DESC, id DESC (1 query)
GET /users/{id}?include=orders -> user + semua ordernya via eager loading (Preload di GORM, with di Fluent; 2 query)
POST /orders -> validasi, simpan, 201 + order baru (user_id positif; total_cents 0..10.000.000; status default pending; note maks 200 karakter); 400 bila tidak valid
PUT /orders/{id} -> baca lalu update status dan updated_at; 404 bila tidak ada
POST /orders/{id}/pay -> satu transaksi: set status paid + insert payments
Error: body {error: pesan}. Semua akses data HARUS lewat ORM, tanpa SQL mentah di kode aplikasi. Tanpa TLS, tanpa kompresi, HTTP/1.1 keep-alive. Aplikasi dikonfigurasi lewat variabel lingkungan (DB host, pool, port, LOG_MODE, LOG_FORMAT, GOGC, GOMEMLIMIT, jumlah event loop, PROFILE).

LOGGING (dua mode di kedua aplikasi: quiet = default benchmark, access)
Go: bungkus slog dengan LogLayer. Kira-kira: sl := slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: levelVar})); log := loglayer.New(loglayer.Config{Transport: llslog.New(llslog.Config{Logger: sl})}); di chi pasang middleware.Recoverer lalu loghttp.Middleware(log, loghttp.Config{}); di handler pakai loghttp.FromRequest(r). Import: go.loglayer.dev/v3, llslog go.loglayer.dev/transports/slog/v3, go.loglayer.dev/integrations/loghttp/v3. quiet = level error (baris akses tersaring, logger per request dan request ID tetap dibuat); access = level info (satu baris 'request completed' per request). LOG_FORMAT=text (default) memakai TextHandler, json memakai JSONHandler. Periksa API versi terpasang sebelum menulis kode.
Swift: pakai SwiftLog bawaan Vapor. Di entrypoint panggil LoggingSystem.bootstrap(from: &env); quiet = LOG_LEVEL=error tanpa middleware log akses; access = LOG_LEVEL=info dan app.middleware.use(RouteLoggingMiddleware(logLevel: .info)). LOG_MODE diterjemahkan ke LOG_LEVEL dan middleware di kode.
Log startup dan error selalu tertulis. Keluaran ke stdout; container memakai driver log Docker 'local' dengan rotasi.

ATURAN KESETARAAN
- Batas CPU dan memori container sama. Go: GOMAXPROCS eksplisit = batas CPU. Swift: jumlah event loop eksplisit = batas CPU.
- Total koneksi DB = 8 x CPU aplikasi (16 di profil mac-m2). Go: SetMaxOpenConns dan SetMaxIdleConns = total. Swift: maxConnectionsPerEventLoop = total / jumlah event loop. Verifikasi di Postgres lewat pg_stat_activity.
- Extended protocol dengan prepared statement di kedua sisi (GORM PrepareStmt: true; verifikasi sisi Swift lewat pg_stat_statements).
- JSON: library idiomatik bawaan (encoding/json Go 1.27; Foundation JSONEncoder/JSONDecoder lewat Vapor Content).
- Build image Linux: Go CGO_ENABLED=0 -trimpath -ldflags='-s -w'; Swift swift build -c release --static-swift-stdlib; runtime pada Distroless atau Alpine (lihat BASE IMAGE). Tuning runtime default (GOGC default, tanpa GOMEMLIMIT).
- Tidak ada optimasi sepihak. Tuning hanya lewat varian tuned (lihat S13).
- Hanya satu aplikasi aktif pada satu waktu; DB direset dari template dan container di-restart sebelum setiap run; urutan Go/Swift diselang-seling dan diacak.

INFRA COMPOSE (profil mac-m2)
VM Docker 8 vCPU / 8 GB. Aplikasi 2 CPU / 1 GB; postgres 2 CPU / 2 GB; k6 2 CPU / 1 GB; sampler kecil (128 MB). Pakai cpuset untuk memisahkan vCPU antar peran dan jaringan Docker internal; k6 menembak aplikasi lewat nama service, bukan port publish. Port publish (go 8080, swift 8081) hanya untuk pengembangan dan profiling. Go mengekspos runtime/metrics di port admin 6060 (tidak dipublish saat benchmark). Profil opsional 'monitoring' (cAdvisor, Prometheus, Grafana) mati secara default. Sediakan juga profil linux-medium (4/4/4 CPU; memori 2/4/2 GB) sebagai opsi. docker-compose.tuned.yml adalah override untuk varian tuned.

K6 (grafana/k6 seri 2.x, di container)
Satu invokasi k6 per titik ukur dengan --summary-export ke results/raw/<run-id>/ (tanpa keluaran per request). Skrip di loadtest/ per skenario, PRNG ber-seed tetap, ID diambil dari loadtest/data. Hanya pakai executor yang masih dipelihara di k6 v2.
Skenario: S1 GET /bench/json; S2 POST /bench/echo; S3 GET /users/{id}; S4 GET /users/{id}/orders; S5 GET /users/{id}?include=orders; S6 POST /orders; S7 PUT /orders/{id}; S8 campuran (50% S3, 20% S4, 10% S5, 10% S6, 10% S7). P1: S9 POST /orders/{id}/pay (ID dari pending_order_ids); S10 soak 20 menit dari S8 pada 70% RPS saturasi; S11 biaya logging: S8 pada laju tetap 50% RPS saturasi, mode quiet lalu access; S12 startup dan cold start; S13 varian tuned.
Tahap (profil mac-m2): warm-up 20 detik tidak dihitung; A = tangga konkurensi closed-loop (constant-vus) 16,32,64,128,256 VU, 10 detik ramp + 30 detik steady; B = laju tetap open-loop (constant-arrival-rate, preAllocatedVUs dan maxVUs cukup) pada 25%, 50%, 75% RPS saturasi implementasi yang lebih lambat, 60 detik tiap titik. Profil linux-medium: tangga 8..512 VU, 15+60 detik, tahap B 90 detik.
Titik saturasi = RPS tertinggi dengan error rate < 0,1% dan p99 < SLO_P99_MS (default 250). Ulangan default 3 (REPEATS). Buang dan ulangi run bila CPU k6 > 80% atau status thermal menunjukkan throttling (pmset -g therm).

S12 - UKURAN IMAGE, STARTUP, COLD START (10 ulangan per stack)
Ukur: ukuran image (docker image inspect) dan jumlah layer, ukuran binary di dalam image; waktu dari pembuatan container (image ada, Postgres hidup) sampai respons 200 pertama /healthz dengan polling 10 ms dari container di jaringan yang sama; latensi request pertama ke S1, S3, S4, S6 (urutan tetap) sebelum warm-up; memori container 5 detik setelah siap dan setelah 100 request pertama. Tiap ulangan me-restart container dan mereset DB dari template bila perlu. Target: make startup-bench; keluaran results/raw/startup/. Laporan menyebut bahwa waktu start mencakup overhead Docker yang sama untuk kedua stack.

S13 - VARIAN TUNED (dilaporkan terpisah dari default)
Tulis tuning/variants.yaml: maksimal tiga perubahan per stack, tiap perubahan dengan alasan, sumber dokumentasi, dan bukti verifikasi bahwa didukung versi terpasang. Kandidat Go: GOMEMLIMIT sekitar 80% batas memori dan GOGC lebih tinggi; PGO memakai profil dari make profile. Kandidat Swift: event loop 2x CPU dibanding 1x CPU; flag compiler tambahan yang terdokumentasi aman dan terbukti tersedia. Dilarang memakai flag yang mematikan pemeriksaan keamanan (mis. -Ounchecked). Jalankan S3, S4, S8 (tahap A dan B) dengan VARIANT=tuned lewat docker-compose.tuned.yml, plus sapuan ukuran pool total 8,16,32,64 (sama untuk kedua stack) pada S3 dan S8 tahap A. Perubahan yang tidak bisa diverifikasi dibuang dan dicatat di Deviasi. Konfigurasi default tidak boleh berubah. Target: make bench-tuned.

BUILD TIME (native macOS, bukan Docker)
Skenario: B1 build bersih tanpa cache; B2 build ulang setelah ubah satu file; B3 dependency ter-cache (sumber dependency ada, artefak kompilasi dibuang). Konfigurasi: dev (go build; swift build debug) dan release (go build -trimpath -ldflags='-s -w'; swift build -c release, tanpa --static-swift-stdlib bila macOS tidak mendukung).
B1: GOCACHE dan GOMODCACHE baru dan kosong (go mod download lalu go build); SwiftPM dengan --scratch-path dan --cache-path baru dan kosong (swift package resolve lalu swift build). Laporkan total dan rincian unduh vs kompilasi.
B2: cache hangat dan hasil build ada; ubah satu string literal di file handler yang setara di kedua aplikasi (mis. teks di handler /healthz), build, lalu kembalikan file. Verifikasi hash binary berubah.
B3: Go: go clean -cache (module cache dipertahankan) lalu go build; Swift: swift package clean lalu swift build.
Aturan: semua cache di direktori sementara berakhiran .noindex; JANGAN menghapus atau mengubah cache global pengguna. Paralelisme default toolchain (tanpa -j), catat hw.ncpu. Ukur dengan /usr/bin/time -l lewat tools/buildtime (wall, user, sys, peak RSS, ukuran binary, paralelisme efektif). Ulangan: B1 3, B2 5, B3 3 (BUILD_REPEATS); urutan Go/Swift diselang-seling; jeda sampai pmset -g therm normal; bungkus caffeinate -dims; tidak ada container benchmark berjalan bersamaan. Build gagal membatalkan run. Pastikan compilation caching SwiftPM tidak aktif. Target: build-bench, build-bench-clean, build-bench-incr, build-bench-cached; variabel BUILD_REPEATS dan BUILD_CONFIG=dev|release|both. Waktu build image Docker TIDAK diukur.

PROFILING (run terpisah, aplikasi native, hanya untuk menjelaskan selisih)
make profile APP=go|swift SCENARIO=s8 DURATION=45: jalankan aplikasi native (konfigurasi release) dengan Postgres Docker di localhost, k6 di container menembak lewat host.docker.internal pada laju tetap 50% RPS saturasi. Go: net/http/pprof di port admin 6060 hanya bila PROFILE=1; simpan profil CPU 45 detik dan snapshot heap, allocs, goroutine (.pb.gz plus SVG). Swift: sample <pid> 45 (bawaan macOS) untuk call tree teks, dan xctrace Time Profiler bila tersedia. Keluaran results/profiles/<app>/<skenario>/. Laporan memuat 10 fungsi teratas per stack dari data profil, berlabel 'penjelasan, bukan perbandingan'. Jangan menyimpulkan penyebab selisih secara otomatis; narasi hanya bila didukung langsung oleh data profil. Profiler tidak pernah aktif saat run pengukuran.

BASE IMAGE (IMAGE_FLAVOR=distroless atau alpine, default distroless)
Image runtime semua komponen buatan kita HARUS Distroless atau Alpine; tahap build bebas. Go (CGO nonaktif, binary statis): gcr.io/distroless/static-debian13:nonroot (atau tag debian12 bila arm64 tidak ada); flavor alpine: Alpine stabil terbaru. Swift: gcr.io/distroless/cc-debian13:nonroot (glibc) dengan binary --static-swift-stdlib; flavor alpine: binary dari Static Linux SDK (musl) di Alpine. Postgres: postgres:<versi>-alpine. Sampler: Alpine kecil. Aplikasi berjalan non-root. Distroless tidak punya shell: health check dari container probe di jaringan Docker, bukan docker exec. Buktikan kecocokan dengan menjalankan binary di image; jika Swift gagal di Distroless glibc dan terpaksa Alpine musl, beri label musl di laporan dan jelaskan risiko alokator. Buat go-app/Dockerfile dan Dockerfile.alpine, swift-app/Dockerfile dan Dockerfile.alpine; make bench IMAGE_FLAVOR=alpine menjalankan flavor Alpine. S12 mengukur ukuran image dan startup untuk kedua flavor bila keduanya berhasil dibangun.

ARSITEKTUR KODE (monorepo modular, lapisan setara)
Go: satu module dengan internal/domain (model, validasi), internal/store (repositori GORM), internal/httpapi (chi, handler, middleware), internal/platform (config, logging LogLayer, pool DB), dan cmd/server. Swift: satu paket SwiftPM dengan target Domain, Persistence (Fluent), HTTPAPI (Vapor), Platform, dan executable App. Dependency satu arah (HTTPAPI ke Persistence ke Domain; Platform dipakai dari atas), tanpa dependency melingkar. Repositori ORM dan handler dipisah lewat antarmuka kecil agar test bisa memakai repositori palsu. make contract memeriksa daftar paket dan target.

DEVELOPER EXPERIENCE (make dx-bench; native macOS, cache terisolasi, tidak bersamaan dengan beban Docker)
DX1 edit sampai siap: ubah satu file, build B2 dev, start proses native, ukur sampai /healthz 200. DX2 waktu test suite: tulis suite paritas minimal 20 kasus identik (validasi, JSON, handler dengan repositori palsu) dengan daftar kasus bersama di contract-tests/parity-cases dan cek jumlah kasus sama di kedua suite; ukur go test ./... vs swift test (pilih satu framework test Swift dan catat) pada kondisi cache kosong dan hangat. DX3 ukuran kode: baris non-kosong non-komentar, jumlah file, dependency langsung dan transitif (go list -m all; swift package show-dependencies atau Package.resolved), ukuran cache dependency. DX4 diagnostik compiler: terapkan tiga mutasi baku pada salinan sementara (tipe tidak cocok, simbol tidak terdefinisi, error tidak ditangani), simpan keluaran compiler apa adanya di results/raw/dx/diagnostics/ beserta jumlah baris dan apakah menunjuk lokasi yang benar; tanpa skor. DX5 onboarding: dari clone bersih sampai request pertama sukses: jumlah perintah, jumlah prasyarat terpasang (dari make doctor), waktu (B1 dev + start native). Ulangan mengikuti BUILD_REPEATS; hasil di results/raw/dx/.

SKALABILITAS
SC1/S14 (make scale-bench): batas CPU aplikasi SCALE_CPUS (default 1,2,3) dengan GOMAXPROCS dan event loop sama dengan CPU dan pool 8 x CPU; jalankan S3 dan S8 tahap A; hitung efisiensi RPS(n)/(n x RPS(1)); tandai 'terbatas DB' bila CPU Postgres >= 90%; kesimpulan hanya untuk 1 sampai 3 core. SC2: dari data tahap A hitung kemiringan memori puncak per 100 VU, pertumbuhan thread per VU, dan titik lutut latensi.
SC3/M1 (make modular-bench): tools/modgen membuat proyek sintetis di direktori sementara berakhiran .noindex dengan N modul (MODULES, default 1,5,20; 50 opsional), tiap modul sekitar 100 baris (model, validasi, handler) dan bergantung hanya pada modul inti, memakai dependency yang sama dengan aplikasi dalam keadaan ter-cache. Dua topologi per stack: T1 satu module atau paket (Go: satu module dengan N package; Swift: satu paket dengan N target) dan T2 banyak module atau paket (Go: N module dalam go.work; Swift: N paket lokal lewat path). Ukur B3 (dependency ter-cache), B2-leaf (ubah satu modul daun), dan B2-core (ubah modul inti) pada konfigurasi dev, native macOS, cache terisolasi. Keluaran di results/raw/modular/. Cetak estimasi durasi sebelum mulai. Jangan menyentuh kode aplikasi utama.

PENGUMPULAN METRIK
- Container sampler membaca cgroup v2 tiap 1 detik untuk container yang diuji: cpu.stat (usage, user, system, throttled), memory.current, memory.peak, memory.stat, pids.current, plus /proc/<pid> untuk thread, FD, context switch, net/dev, io.stat. Tulis CSV per run. Pembanding silang: docker stats. Fallback ke docker stats bila cgroup tak terbaca (tandai di laporan).
- Go: endpoint admin 6060 untuk runtime/metrics (goroutine, siklus GC, jeda GC, heap).
- Postgres: snapshot pg_stat_statements, pg_stat_database, pg_stat_activity sebelum dan sesudah run; reset statistik antar run.
- Logging: jumlah baris dan byte log per request.
- Statik: ukuran image dan binary, waktu start sampai /healthz OK (S12).
- Metadata per run: model Mac, sw_vers, jumlah core, ukuran VM Docker, versi Docker, ulimit -n, digest image, status thermal sebelum dan sesudah.

MAKEFILE (satu pintu masuk; GNU Make 3.81; semua target punya komentar '## deskripsi' dan make help mencetaknya)
Variabel: APP=go|swift|both (default both), SCENARIO=daftar (mis. s1,s3,s8) | core | all, REPEATS=3, PROFILE=mac-m2, SLO_P99_MS=250, LOG_MODE=quiet|access, LOG_FORMAT=text|json (hanya Go), VARIANT=default|tuned, BUILD_REPEATS, BUILD_CONFIG=dev|release|both, DURATION=45, IMAGE_FLAVOR=distroless|alpine, SCALE_CPUS=1,2,3, MODULES=1,5,20. Baca .env bila ada.
Target: help, doctor, db-up, db-down, db-seed, db-reset, db-psql, go-build, go-run, go-test, go-image, go-up, go-down, go-logs, swift-build, swift-run, swift-test, swift-image, swift-up, swift-down, swift-logs, contract, bench-smoke, bench-core (S1,S3,S4,S8), bench, bench-tuned, startup-bench, build-bench, build-bench-clean, build-bench-incr, build-bench-cached, profile, dx-bench, scale-bench, modular-bench, report, clean, clean-all.
doctor: cek arm64, versi Docker, ukuran VM Docker, image arm64, akses sampler ke cgroup, toolchain native Go 1.27.2 dan Swift 6.4, charger (pmset -g batt), Low Power Mode, status thermal. go-build dan go-run native di Mac (Postgres dari db-up); swift-build dan swift-run native bila toolchain Swift 6.4 ada, jika tidak jatuh ke container dan catat di README. go-up dan swift-up menjalankan container dengan batas profil. Benchmark beban selalu di container dan dibungkus caffeinate -dims bila tersedia. Logika panjang di tools/ (Python 3 atau bash), Makefile tetap ringkas dan terbaca.

LAPORAN (hasil di results/)
Agregasi ulangan: median, min, max, CV%; tandai CV > 5%. Hasilkan results/report.md, CSV agregat, dan grafik PNG (RPS vs konkurensi, latensi vs laju, CPU dan memori vs waktu, build time per skenario). Metrik turunan: CPU-ms per request, RPS per core terpakai, RPS per GB memori puncak, p99 dan memori pada laju tetap yang sama, jumlah query per request, biaya logging per stack (selisih quiet vs access), rasio Swift/Go dengan rentang. Bagian tambahan: tabel build time B1-B3 (dev dan release) dengan wall, CPU, peak RSS, ukuran binary; ukuran image dan startup; default vs tuned berdampingan beserta selisih (kesimpulan utama hanya dari default); 10 fungsi teratas dari profil. Cantumkan versi, konfigurasi, checksum seed, peringatan validitas, dan label: angka beban 'Apple Silicon, Docker Desktop VM: hasil relatif, bukan absolut'; angka build time dan profil 'macOS native'. Hasil tidak boleh dibandingkan dengan mesin lain.
BAGIAN KESIMPULAN (disusun tools/report dari data): ringkasan DX dan skalabilitas; matriks kriteria (B1-B3 dev dan release, DX1, DX2, DX3, DX5, startup dan ukuran image, efisiensi S14, kemiringan memori SC2, kemiringan M1 per topologi) dengan median Go, median Swift, rentang, dan hasil; rekomendasi monorepo vs modular yang kondisional per stack; bagian 'Tidak diukur' (kematangan ekosistem, IDE dan debugging, ketersediaan engineer, stabilitas rilis) dengan sumber atau label 'dari pengetahuan umum', tanpa bobot; batas kesimpulan. Aturan: satu stack dinyatakan lebih baik hanya bila rentang min-maks kedua stack tidak tumpang tindih dan selisih median > 5%; selain itu tulis 'setara' atau 'belum cukup bukti'. Setiap kalimat kesimpulan menunjuk metrik; DX4 tanpa skor; rekomendasi hanya untuk rentang N yang diuji; jangan menyimpulkan penyebab tanpa dukungan profil atau dokumentasi yang dikutip.

GERBANG KESETARAAN (make contract; gagal = benchmark berhenti)
1. Kontrak: status dan bentuk JSON sama dengan golden JSON dari fixture di kedua aplikasi, termasuk 400 dan 404.
2. Jumlah query per request sama di tiap endpoint (dari pg_stat_statements).
3. Konfigurasi: pool, thread, dan batas container saat runtime sama dengan rencana. Logging: mode quiet tidak menulis baris akses; mode access menulis tepat satu baris per request di kedua aplikasi.
4. Data: checksum tabel setelah seed sama dengan db/checksums.txt.
Jika gerbang gagal, perbaiki kode aplikasi; jangan melonggarkan gerbang.

URUTAN KERJA
1) Langkah 0. 2) Scaffold repo, Makefile awal, dan compose. 3) DB, seed, fixture, checksum. 4) go-app (arsitektur modular, logging, knob konfigurasi, pprof bersyarat, Dockerfile distroless dan alpine). 5) swift-app (arsitektur modular, logging, knob konfigurasi, Dockerfile distroless dan alpine). 6) contract-tests; jalankan make contract sampai lulus. 7) loadtest, sampler, orkestrator, agregator. 8) tools/buildtime dan target build-bench; jalankan versi pendek (1 ulangan) untuk membuktikan B1-B3 berjalan bila toolchain native ada. 9) startup-bench, varian tuned, profile, dx-bench, scale-bench, dan modular-bench (masing-masing uji singkat). 10) Jalankan make bench-smoke sampai selesai dan report.md terbentuk. 11) README (syarat Mac, cara menjalankan, cara membaca hasil, Asumsi, Deviasi, Lingkungan terverifikasi) dan docs. Verifikasi tiap tahap sebelum lanjut. Jangan menjalankan make bench penuh atau build-bench penuh (butuh berjam-jam): pastikan siap dijalankan dan cetak estimasi durasinya.

ATURAN KERAS
- Jangan mengarang angka: semua angka di laporan harus dari run nyata. Angka smoke diberi label 'smoke, bukan final'.
- Jangan melemahkan gerbang kesetaraan agar tes lolos.
- Jangan memakai SQL mentah di kode aplikasi, caching, atau optimasi tidak idiomatik di salah satu sisi.
- Jangan memakai Vapor 5 di stack utama. Jangan mengubah pengaturan Docker Desktop atau macOS, dan jangan menghapus atau mengubah cache global Go atau SwiftPM milik pengguna.
- Jangan memasang toolchain atau paket sistem tanpa izin; tulis petunjuknya di make doctor.
- Jangan menyimpulkan DX atau skalabilitas tanpa data yang lolos aturan Kesimpulan, jangan menyamarkan faktor tidak terukur sebagai temuan, dan jangan memakai image runtime selain Distroless atau Alpine.

OPSIONAL (hanya setelah semua di atas lulus)
Tambah varian swift-app-v5 (Vapor 5 beta, Swift 6.4, FluentKit langsung seperti template cabang vapor5) berlabel EKSPERIMENTAL. Jika gagal dibangun, lewati dan catat di README.

KELUARAN AKHIR
Ringkasan singkat: versi persis yang terpakai, hasil make doctor dan make contract, ringkasan make bench-smoke (berlabel smoke), status build-bench dan profile (jalan atau ditolak doctor), daftar Asumsi dan Deviasi, dan perintah untuk menjalankan benchmark penuh (mis. make bench APP=both SCENARIO=core, make build-bench, make startup-bench, make bench-tuned, make profile APP=go SCENARIO=s8).
```
