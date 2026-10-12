-- Satu-satunya sumber skema. Aplikasi tidak boleh membuat/mengubah tabel (tanpa AutoMigrate, tanpa migrasi Fluent).
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE users (
    id         bigserial PRIMARY KEY,
    name       text        NOT NULL,
    email      text        NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE orders (
    id          bigserial PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES users (id),
    status      text        NOT NULL,
    total_cents int         NOT NULL,
    note        text        NOT NULL DEFAULT '',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE payments (
    id           bigserial PRIMARY KEY,
    order_id     bigint      NOT NULL REFERENCES orders (id),
    amount_cents int         NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX orders_user_id_created_at_idx ON orders (user_id, created_at DESC);
CREATE INDEX orders_status_id_idx ON orders (status, id);
