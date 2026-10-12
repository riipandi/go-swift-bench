#!/usr/bin/env bash
# Operasi database. Pakai: tools/db.sh up|down|wait|seed|reset|fixture|fixture-reset|verify|psql|stats-reset
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
. "$ROOT/tools/lib/env.sh"
PGC=bench-postgres
DC="$ROOT/tools/dc.sh"

psql_admin() { docker exec -i "$PGC" psql -v ON_ERROR_STOP=1 -q -U bench -d "${DB:-postgres}" "$@"; }

wait_pg() {
  local i
  for i in $(seq 1 60); do
    if docker exec "$PGC" pg_isready -U bench -d postgres >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Postgres tidak siap" >&2; return 1
}

recreate_from_template() { # <db> <template>
  DB=postgres psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$1','$2') AND pid <> pg_backend_pid();" >/dev/null
  DB=postgres psql_admin -c "DROP DATABASE IF EXISTS $1" -c "CREATE DATABASE $1 TEMPLATE $2"
}

checksums() { # <db> -> baris "tabel jumlah_baris md5"
  DB=$1 psql_admin -At -F ' ' <<'SQL'
SET TimeZone = 'UTC'; SET DateStyle = 'ISO, MDY'; SET extra_float_digits = 1;
SELECT 'users', count(*), coalesce(md5(string_agg(t::text, E'\n' ORDER BY id)), 'empty') FROM users t;
SELECT 'orders', count(*), coalesce(md5(string_agg(t::text, E'\n' ORDER BY id)), 'empty') FROM orders t;
SELECT 'payments', count(*), coalesce(md5(string_agg(t::text, E'\n' ORDER BY id)), 'empty') FROM payments t;
SQL
}

export_ids() { # <db>
  mkdir -p "$ROOT/loadtest/data"
  DB=$1 psql_admin -At -c "SELECT json_agg(id ORDER BY id) FROM users" > "$ROOT/loadtest/data/user_ids.json"
  DB=$1 psql_admin -At -c "SELECT json_agg(id ORDER BY id) FROM orders WHERE id % 10 = 0" > "$ROOT/loadtest/data/order_ids.json"
  DB=$1 psql_admin -At -c "SELECT json_agg(id ORDER BY id) FROM orders WHERE status = 'pending'" > "$ROOT/loadtest/data/pending_order_ids.json"
}

cmd=${1:-}
case "$cmd" in
  up)
    "$DC" up -d --wait postgres
    ;;
  down)
    "$DC" stop postgres
    ;;
  wait) wait_pg ;;
  seed)
    wait_pg
    DB=postgres psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('bench','bench_tpl') AND pid <> pg_backend_pid();" >/dev/null
    DB=postgres psql_admin -c "DROP DATABASE IF EXISTS bench" -c "DROP DATABASE IF EXISTS bench_tpl" -c "CREATE DATABASE bench"
    echo "== schema"; DB=bench psql_admin < "$ROOT/db/schema.sql"
    echo "== seed (10.000 user, 500.000 order)"; DB=bench psql_admin < "$ROOT/db/seed.sql" >/dev/null
    echo "== VACUUM ANALYZE"; DB=bench psql_admin -c "VACUUM ANALYZE"
    echo "== checksum"
    tmp=$(mktemp); checksums bench > "$tmp"; cat "$tmp"
    if [ -f "$ROOT/db/checksums.txt" ] && [ "${UPDATE_CHECKSUMS:-0}" != "1" ]; then
      if diff -u "$ROOT/db/checksums.txt" "$tmp"; then echo "checksum COCOK dengan db/checksums.txt"
      else echo "checksum TIDAK COCOK (UPDATE_CHECKSUMS=1 hanya bila seed memang sengaja diubah)" >&2; rm -f "$tmp"; exit 1; fi
    else
      cp "$tmp" "$ROOT/db/checksums.txt"; echo "db/checksums.txt ditulis"
    fi
    rm -f "$tmp"
    echo "== ekspor ID"; export_ids bench
    echo "== template bench_tpl"
    DB=postgres psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'bench' AND pid <> pg_backend_pid();" >/dev/null
    DB=postgres psql_admin -c "CREATE DATABASE bench_tpl TEMPLATE bench"
    ;;
  reset)
    wait_pg
    recreate_from_template bench bench_tpl
    ;;
  fixture)
    wait_pg
    DB=postgres psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('fixture','fixture_tpl') AND pid <> pg_backend_pid();" >/dev/null
    DB=postgres psql_admin -c "DROP DATABASE IF EXISTS fixture" -c "DROP DATABASE IF EXISTS fixture_tpl" -c "CREATE DATABASE fixture"
    DB=fixture psql_admin < "$ROOT/db/schema.sql"
    DB=fixture psql_admin < "$ROOT/db/fixtures/fixture.sql" >/dev/null
    DB=fixture psql_admin -c "VACUUM ANALYZE"
    DB=postgres psql_admin -c "CREATE DATABASE fixture_tpl TEMPLATE fixture"
    ;;
  fixture-reset)
    wait_pg
    recreate_from_template fixture fixture_tpl
    ;;
  verify) # checksum bench_tpl harus sama dengan db/checksums.txt (gerbang 4)
    tmp=$(mktemp); checksums bench_tpl > "$tmp"
    if diff -u "$ROOT/db/checksums.txt" "$tmp"; then echo "OK: checksum bench_tpl == db/checksums.txt"; rm -f "$tmp"
    else echo "GAGAL: checksum tidak cocok" >&2; rm -f "$tmp"; exit 1; fi
    ;;
  stats-reset)
    DB=${DB_NAME:-bench} psql_admin -c "SELECT pg_stat_statements_reset()" -c "SELECT pg_stat_reset()" >/dev/null
    ;;
  psql)
    shift
    exec docker exec -it "$PGC" psql -U bench -d "${DB_NAME:-bench}" "$@"
    ;;
  *) echo "pakai: $0 up|down|wait|seed|reset|fixture|fixture-reset|verify|stats-reset|psql" >&2; exit 2 ;;
esac
