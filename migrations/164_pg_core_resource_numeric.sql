-- 164_pg_core_resource_numeric.sql
-- GC-BACKEND: postgres
-- P0-A1: authoritative gameplay resources + trader amounts become exact,
-- unconstrained PostgreSQL NUMERIC. SQLite intentionally keeps its legacy REAL
-- compatibility path; migration_history is not copied during PG cutover.

ALTER TABLE planets ALTER COLUMN metal DROP DEFAULT;
ALTER TABLE planets ALTER COLUMN metal TYPE NUMERIC USING TRUNC(metal::numeric);
ALTER TABLE planets ALTER COLUMN metal SET DEFAULT 0;

ALTER TABLE planets ALTER COLUMN crystal DROP DEFAULT;
ALTER TABLE planets ALTER COLUMN crystal TYPE NUMERIC USING TRUNC(crystal::numeric);
ALTER TABLE planets ALTER COLUMN crystal SET DEFAULT 0;

ALTER TABLE planets ALTER COLUMN fuel_cells DROP DEFAULT;
ALTER TABLE planets ALTER COLUMN fuel_cells TYPE NUMERIC USING TRUNC(fuel_cells::numeric);
ALTER TABLE planets ALTER COLUMN fuel_cells SET DEFAULT 0;

ALTER TABLE planets ALTER COLUMN fuel_exchange_daily_used DROP DEFAULT;
ALTER TABLE planets ALTER COLUMN fuel_exchange_daily_used TYPE NUMERIC USING TRUNC(fuel_exchange_daily_used::numeric);
ALTER TABLE planets ALTER COLUMN fuel_exchange_daily_used SET DEFAULT 0;

ALTER TABLE players ALTER COLUMN exchange_daily_used DROP DEFAULT;
ALTER TABLE players ALTER COLUMN exchange_daily_used TYPE NUMERIC USING TRUNC(exchange_daily_used::numeric);
ALTER TABLE players ALTER COLUMN exchange_daily_used SET DEFAULT 0;

ALTER TABLE exchange_log ALTER COLUMN give_amount DROP DEFAULT;
ALTER TABLE exchange_log ALTER COLUMN give_amount TYPE NUMERIC USING TRUNC(give_amount::numeric);
ALTER TABLE exchange_log ALTER COLUMN give_amount SET DEFAULT 0;

ALTER TABLE exchange_log ALTER COLUMN receive_amount DROP DEFAULT;
ALTER TABLE exchange_log ALTER COLUMN receive_amount TYPE NUMERIC USING TRUNC(receive_amount::numeric);
ALTER TABLE exchange_log ALTER COLUMN receive_amount SET DEFAULT 0;
