#!/usr/bin/env bash
# Cek prasyarat. Pakai: tools/doctor.sh [all|docker|native|prereqs]
#  docker : arm64, Docker, ukuran VM, disk, image arm64, akses sampler ke cgroup  -> gagal = benchmark beban ditolak
#  native : Go 1.27.2, Swift 6.4, xctrace, charger, LPM, thermal                   -> gagal = build-bench/profile ditolak
# Tidak memasang apa pun: hanya mencetak petunjuk.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/tools/lib/env.sh"
SCOPE=${1:-all}
FAILS=0; WARNS=0

ok()   { printf '  [ OK ] %s\n' "$*"; }
warn() { printf '  [WARN] %s\n' "$*"; WARNS=$((WARNS+1)); }
bad()  { printf '  [FAIL] %s\n' "$*"; FAILS=$((FAILS+1)); }
hint() { printf '         -> %s\n' "$*"; }

check_docker() {
  echo "== Docker / benchmark beban (profil $PROFILE)"
  local arch; arch=$(uname -m)
  [ "$arch" = "arm64" ] && ok "uname -m = arm64" || bad "uname -m = $arch (butuh arm64)"
  printf '         %s %s | %s\n' "$(sw_vers -productName 2>/dev/null)" "$(sw_vers -productVersion 2>/dev/null)" "$(sysctl -n hw.model 2>/dev/null)"
  if ! docker info >/dev/null 2>&1; then
    bad "Docker daemon tidak terjangkau"; hint "jalankan Docker Desktop/OrbStack (orbctl start), lalu ulangi"; return
  fi
  local ver ncpu mem cg engine
  ver=$(docker version --format '{{.Server.Version}}' 2>/dev/null)
  engine=$(docker info --format '{{.OperatingSystem}}' 2>/dev/null)
  ok "Docker server $ver ($engine); $(docker compose version --short 2>/dev/null | sed 's/^/compose /')"
  ncpu=$(docker info --format '{{.NCPU}}'); mem=$(docker info --format '{{.MemTotal}}'); cg=$(docker info --format '{{.CgroupVersion}}')
  if [ "$ncpu" -ge "$MIN_VM_CPUS" ]; then ok "VM Docker: $ncpu vCPU (>= $MIN_VM_CPUS)"
  else bad "VM Docker hanya $ncpu vCPU (profil $PROFILE butuh >= $MIN_VM_CPUS)"; hint "Docker Desktop > Settings > Resources (OrbStack: Settings > System). Skrip ini tidak mengubahnya."; fi
  if [ "$mem" -ge "$MIN_VM_MEM_BYTES" ]; then ok "VM Docker: $((mem/1024/1024)) MiB (>= $((MIN_VM_MEM_BYTES/1000000)) MB)"
  else bad "VM Docker hanya $((mem/1024/1024)) MiB (butuh >= $((MIN_VM_MEM_BYTES/1000000)) MB)"; hint "Docker Desktop > Settings > Resources"; fi
  [ "$cg" = "2" ] && ok "cgroup v2" || bad "cgroup v$cg (sampler butuh v2)"
  local free; free=$(df -g "$ROOT" | awk 'NR==2{print $4}')
  if [ "$free" -ge 20 ]; then ok "disk bebas ${free} GiB"
  elif [ "$free" -ge 6 ]; then warn "disk bebas hanya ${free} GiB (disarankan >= 20 GiB; Docker berhenti bila disk penuh)"
  else bad "disk bebas ${free} GiB: terlalu sedikit untuk image dan build"; fi
  # cpuset harus muat di VM
  local maxcpu; maxcpu=$(printf '%s,%s,%s,%s\n' "$APP_CPUSET" "$PG_CPUSET" "$K6_CPUSET" "$SAMPLER_CPUSET" | tr ',-' '\n\n' | sort -n | tail -1)
  [ "$maxcpu" -lt "$ncpu" ] && ok "cpuset profil (maks vCPU $maxcpu) muat di VM" || bad "cpuset profil memakai vCPU $maxcpu >= $ncpu vCPU VM"
  # image arm64
  local var img a
  for var in GO_BUILD_IMAGE SWIFT_BUILD_IMAGE DISTROLESS_STATIC_IMAGE DISTROLESS_CC_IMAGE ALPINE_IMAGE PG_IMAGE K6_IMAGE; do
    img=${!var}
    if a=$(docker image inspect "$img" --format '{{.Architecture}}' 2>/dev/null); then
      [ "$a" = "arm64" ] && ok "$var arm64" || bad "$var arsitektur $a (emulasi ditolak)"
    else warn "$var belum ada lokal (akan ditarik saat dipakai): $img"; fi
  done
  # akses sampler ke cgroup
  if docker image inspect "$ALPINE_IMAGE" >/dev/null 2>&1; then
    docker rm -f bench-doctor-probe >/dev/null 2>&1
    docker run -d --name bench-doctor-probe --cpus 1 --memory 64m "$ALPINE_IMAGE" sleep 30 >/dev/null 2>&1
    local cid pid; cid=$(docker inspect bench-doctor-probe --format '{{.Id}}'); pid=$(docker inspect bench-doctor-probe --format '{{.State.Pid}}')
    if docker run --rm --pid=host --cgroupns=host "$ALPINE_IMAGE" sh -c "cat /sys/fs/cgroup/docker/$cid/cpu.stat >/dev/null && cat /sys/fs/cgroup/docker/$cid/memory.current >/dev/null && cat /proc/$pid/status >/dev/null" >/dev/null 2>&1
    then ok "sampler (pid=host, cgroupns=host) membaca cgroup /sys/fs/cgroup/docker/<id> dan /proc/<pid>"
    else bad "sampler tidak bisa membaca cgroup container lain"; hint "fallback ke 'docker stats' dan ditandai di laporan (fidelitas lebih rendah)"; fi
    docker rm -f bench-doctor-probe >/dev/null 2>&1
  else warn "tidak bisa menguji akses cgroup sampler (image alpine belum ada)"; fi
  # port
  local p
  for p in 54322 8080 8081; do
    if lsof -nP -iTCP:$p -sTCP:LISTEN >/dev/null 2>&1; then
      if docker ps --format '{{.Ports}}' | grep -q ":$p->"; then ok "port $p dipakai container benchmark"
      else warn "port $p dipakai proses lain (publish dev bisa bentrok)"; fi
    fi
  done
}

check_native() {
  echo "== Native macOS / build-bench, profile, dx-bench"
  local gv sv
  if command -v go >/dev/null 2>&1; then
    gv=$(go version)
    case "$gv" in *go1.27.2\ *) ok "$gv" ;; *) warn "$gv (diminta go1.27.2: catat sebagai Deviasi)" ;; esac
  else bad "Go tidak terpasang"; hint "pasang Go 1.27.2 dari https://go.dev/dl/ (skrip ini tidak memasang apa pun) -> build-bench & profile ditolak"; fi
  if command -v swift >/dev/null 2>&1; then
    sv=$(swift --version 2>&1 | head -1)
    case "$sv" in *"Swift version 6.4"*) ok "$sv" ;; *) bad "$sv (butuh Swift 6.4)"; hint "pasang Xcode 27 atau toolchain swift.org 6.4 -> build-bench & profile ditolak" ;; esac
    ok "xcode-select: $(xcode-select -p 2>/dev/null)"
    if xcrun --find xctrace >/dev/null 2>&1; then ok "xctrace tersedia (Time Profiler)"; else warn "xctrace tidak ada: profil Swift hanya 'sample'"; fi
  else bad "Swift tidak terpasang"; hint "pasang Xcode 27 atau toolchain swift.org 6.4 -> build-bench & profile ditolak"; fi
  if pmset -g batt 2>/dev/null | grep -q "AC Power"; then ok "charger tersambung"; else warn "charger TIDAK tersambung (hasil bisa dibatasi daya)"; fi
  if pmset -g 2>/dev/null | grep -Eq "lowpowermode[[:space:]]+1"; then warn "Low Power Mode aktif: matikan sebelum benchmark"; else ok "Low Power Mode mati"; fi
  local th; th=$(pmset -g therm 2>&1)
  if echo "$th" | grep -Eq "CPU_Speed_Limit[[:space:]]*=[[:space:]]*([0-9]|[1-9][0-9])$"; then warn "throttling thermal terdeteksi: $(echo "$th" | grep CPU_Speed_Limit)"
  else ok "status thermal normal (tidak ada pembatasan tercatat)"; fi
  printf '         ulimit -n = %s, hw.ncpu = %s\n' "$(ulimit -n)" "$(sysctl -n hw.ncpu 2>/dev/null)"
}

# daftar prasyarat terpasang (dipakai DX5): satu nama per baris
prereqs() {
  command -v docker >/dev/null 2>&1 && echo docker
  command -v make >/dev/null 2>&1 && echo make
  command -v python3 >/dev/null 2>&1 && echo python3
  command -v go >/dev/null 2>&1 && echo go
  command -v swift >/dev/null 2>&1 && echo swift
}

case "$SCOPE" in
  docker) check_docker ;;
  native) check_native ;;
  prereqs) prereqs; exit 0 ;;
  all) check_docker; check_native ;;
  *) echo "pakai: $0 [all|docker|native|prereqs]" >&2; exit 2 ;;
esac
echo
echo "doctor ($SCOPE): $FAILS gagal, $WARNS peringatan"
[ "$FAILS" -eq 0 ]
