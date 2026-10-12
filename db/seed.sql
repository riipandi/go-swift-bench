-- Seed benchmark deterministik: generate_series + hash md5 (tanpa random()).
-- Mengubah distribusi di sini mengubah checksum; laporan lama tidak boleh dibandingkan dengan yang baru.
SET TimeZone = 'UTC';

-- u in [0,1) deterministik dari kunci teks
CREATE FUNCTION pg_temp.h(key text) RETURNS float8
LANGUAGE sql IMMUTABLE AS
$$ SELECT (('x' || substr(md5(key), 1, 8))::bit(32)::bigint)::float8 / 4294967296.0 $$;

INSERT INTO users (id, name, email, created_at)
SELECT i,
       'User ' || i,
       'user' || i || '@example.test',
       timestamptz '2025-01-01 00:00:00+00' + i * interval '1 minute'
FROM generate_series(1, 10000) AS i;

-- user_id = 1 + floor(10000 * u^1.2); status 20/50/20/10; created_at tersebar 365 hari; total 500..500000
INSERT INTO orders (id, user_id, status, total_cents, note, created_at, updated_at)
SELECT i,
       1 + floor(10000 * power(pg_temp.h('u' || i), 1.2))::bigint,
       CASE WHEN s < 0.2 THEN 'pending'
            WHEN s < 0.7 THEN 'paid'
            WHEN s < 0.9 THEN 'shipped'
            ELSE 'cancelled' END,
       500 + floor(pg_temp.h('t' || i) * 499501)::int,
       'order-' || i || '-' || substr(md5('n' || i), 1, 8),
       ts, ts
FROM (
    SELECT i,
           pg_temp.h('s' || i) AS s,
           timestamptz '2025-01-01 00:00:00+00'
             + floor(pg_temp.h('c' || i) * 31536000)::int * interval '1 second' AS ts
    FROM generate_series(1, 500000) AS i
) AS x;

SELECT setval(pg_get_serial_sequence('users', 'id'), 10000);
SELECT setval(pg_get_serial_sequence('orders', 'id'), 500000);
