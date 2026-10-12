#!/usr/bin/env bash
# Pembungkus docker compose: memuat profil/env, memilih file compose (tuned, dev), lalu menjalankan compose.
# Pakai: tools/dc.sh [--dev] <argumen compose...>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/tools/lib/env.sh"

files=(-f "$ROOT/docker-compose.yml")
if [ "${1:-}" = "--dev" ]; then
  files+=(-f "$ROOT/docker-compose.dev.yml"); shift
fi
if [ "$VARIANT" = "tuned" ]; then
  files+=(-f "$ROOT/docker-compose.tuned.yml")
fi
export GO_DOCKERFILE=Dockerfile
export SWIFT_DOCKERFILE=Dockerfile
export GO_RUNTIME_IMAGE=$DISTROLESS_STATIC_IMAGE
export SWIFT_RUNTIME_IMAGE=$DISTROLESS_CC_IMAGE
if [ "$IMAGE_FLAVOR" = "alpine" ]; then
  GO_DOCKERFILE=Dockerfile.alpine
  SWIFT_DOCKERFILE=Dockerfile.alpine
  GO_RUNTIME_IMAGE=$ALPINE_IMAGE
  SWIFT_RUNTIME_IMAGE=$ALPINE_IMAGE
elif [ "$IMAGE_FLAVOR" != "distroless" ]; then
  echo "IMAGE_FLAVOR harus distroless atau alpine" >&2; exit 2
fi
if [ "$VARIANT" = "tuned" ]; then
  # nilai turunan varian tuned (lihat tuning/variants.yaml); default tidak terpengaruh
  mem=$APP_MEM; num=${mem%[gGmM]}; unit=${mem#$num}
  case "$unit" in g|G) mib=$((num * 1024)) ;; *) mib=$num ;; esac
  export TUNED_GOMEMLIMIT="$((mib * 80 / 100))MiB"
  export TUNED_GOGC=${TUNED_GOGC:-400}
  export TUNED_EVENT_LOOPS=$((2 * APP_CPUS))
  export TUNED_SWIFT_FLAGS=${TUNED_SWIFT_FLAGS:--Xswiftc -cross-module-optimization}
  if [ -f "$ROOT/go-app/pgo/default.pgo" ]; then export GO_PGO=1; fi
fi
exec docker compose "${files[@]}" --profile apps --profile tools "$@"
