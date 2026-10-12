#!/usr/bin/env bash
# Memuat konfigurasi. Prioritas: environment (termasuk variabel make) > .env > profil > images.env.
# Dipakai dengan: . tools/lib/env.sh   (ROOT harus sudah diset atau dihitung di sini)

ROOT=${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}

_load_defaults() {
  local file=$1 line k v
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    k=${line%%=*}
    v=${line#*=}
    # hanya set bila belum ada di environment
    if [ -z "${!k+x}" ]; then export "$k=$v"; fi
  done < "$file"
}

_load_defaults "$ROOT/.env"
PROFILE=${PROFILE:-mac-m2}
export PROFILE
if [ ! -f "$ROOT/profiles/$PROFILE.conf" ]; then
  echo "profil tidak dikenal: $PROFILE (lihat profiles/)" >&2
  return 1 2>/dev/null || exit 1
fi
_load_defaults "$ROOT/profiles/$PROFILE.conf"
_load_defaults "$ROOT/profiles/images.conf"

export IMAGE_FLAVOR=${IMAGE_FLAVOR:-distroless}
export VARIANT=${VARIANT:-default}
export LOG_MODE=${LOG_MODE:-quiet}
export LOG_FORMAT=${LOG_FORMAT:-text}
export SLO_P99_MS=${SLO_P99_MS:-250}
export REPEATS=${REPEATS:-3}
export DB_POOL_TOTAL=${DB_POOL_TOTAL:-$((8 * APP_CPUS))}
export EVENT_LOOPS=${EVENT_LOOPS:-$APP_CPUS}
export GOMAXPROCS_APP=${GOMAXPROCS_APP:-$APP_CPUS}
export ROOT
