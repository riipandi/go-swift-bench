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
exec docker compose "${files[@]}" --profile apps --profile tools "$@"
