-- 167_pg_unit_amounts_bigint.sql
-- GC-BACKEND: postgres
-- P0-B2: queue/stock quantities that currently fall through SQLite INTEGER
-- into PostgreSQL int4 become at-least-i64 safe. Paid queue cost snapshots are
-- deliberately left for P0-C.

ALTER TABLE defense_queue
    ALTER COLUMN amount TYPE BIGINT USING amount::bigint;

ALTER TABLE planet_troops
    ALTER COLUMN amount TYPE BIGINT USING amount::bigint;

ALTER TABLE troop_queue
    ALTER COLUMN amount TYPE BIGINT USING amount::bigint;
