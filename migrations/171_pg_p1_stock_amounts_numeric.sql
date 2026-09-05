-- 171_pg_p1_stock_amounts_numeric.sql
-- GC-BACKEND: postgres
-- P1-B: persistent ship/defense stocks and shipyard order quantities are
-- no-max gameplay integers. BIGINT only postpones overflow; NUMERIC removes it.

ALTER TABLE planet_ships
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;

ALTER TABLE shipyard_queue
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;

ALTER TABLE planet_defense
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;
