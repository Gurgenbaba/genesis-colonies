-- 174_pg_core_resource_numeric_constraints.sql
-- GC-BACKEND: postgres
-- Rebuild core planet resource CHECK constraints after the REAL -> NUMERIC
-- migration. Constraints created while columns were DOUBLE PRECISION may retain
-- float8 casts internally and overflow when validating huge NUMERIC values.

ALTER TABLE planets DROP CONSTRAINT IF EXISTS planets_metal_check;
ALTER TABLE planets DROP CONSTRAINT IF EXISTS planets_crystal_check;
ALTER TABLE planets DROP CONSTRAINT IF EXISTS planets_fuel_cells_check;

ALTER TABLE planets
    ADD CONSTRAINT planets_metal_check CHECK (metal >= CAST(0 AS NUMERIC));
ALTER TABLE planets
    ADD CONSTRAINT planets_crystal_check CHECK (crystal >= CAST(0 AS NUMERIC));
ALTER TABLE planets
    ADD CONSTRAINT planets_fuel_cells_check CHECK (fuel_cells >= CAST(0 AS NUMERIC));
