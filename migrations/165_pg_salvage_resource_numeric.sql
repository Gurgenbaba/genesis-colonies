-- 165_pg_salvage_resource_numeric.sql
-- GC-BACKEND: postgres
-- P0-A2: debris + asteroid resource pools/claim ledgers become exact,
-- unconstrained PostgreSQL NUMERIC.

ALTER TABLE debris_fields
    ALTER COLUMN metal TYPE NUMERIC USING TRUNC(metal::numeric);
ALTER TABLE debris_fields
    ALTER COLUMN crystal TYPE NUMERIC USING TRUNC(crystal::numeric);

ALTER TABLE asteroid_fields
    ALTER COLUMN metal TYPE NUMERIC USING TRUNC(metal::numeric);
ALTER TABLE asteroid_fields
    ALTER COLUMN crystal TYPE NUMERIC USING TRUNC(crystal::numeric);
ALTER TABLE asteroid_fields
    ALTER COLUMN fuel_cells TYPE NUMERIC USING TRUNC(fuel_cells::numeric);

ALTER TABLE asteroid_field_claims
    ALTER COLUMN metal TYPE NUMERIC USING TRUNC(metal::numeric);
ALTER TABLE asteroid_field_claims
    ALTER COLUMN crystal TYPE NUMERIC USING TRUNC(crystal::numeric);
ALTER TABLE asteroid_field_claims
    ALTER COLUMN fuel_cells TYPE NUMERIC USING TRUNC(fuel_cells::numeric);
