-- 172_pg_p1_planet_economy_numeric.sql
-- GC-BACKEND: postgres
-- P1-C: Planet Evolution economic balances and rates must remain exact and
-- unbounded. Rates are fractional by design, so use unconstrained NUMERIC
-- rather than BIGINT or DOUBLE PRECISION.

ALTER TABLE planet_special_resources
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;
ALTER TABLE planet_special_resources
    ALTER COLUMN cap TYPE NUMERIC USING cap::numeric;
ALTER TABLE planet_special_resources
    ALTER COLUMN production_per_hour TYPE NUMERIC USING production_per_hour::numeric;
ALTER TABLE planet_special_resources
    ALTER COLUMN consumption_per_hour TYPE NUMERIC USING consumption_per_hour::numeric;

ALTER TABLE planet_trade_routes
    ALTER COLUMN amount_per_hour TYPE NUMERIC USING amount_per_hour::numeric;

ALTER TABLE planet_import_demands
    ALTER COLUMN required_per_hour TYPE NUMERIC USING required_per_hour::numeric;

-- Definition magnitudes feed the live columns above and therefore must not
-- reintroduce binary-float rounding at the source.
ALTER TABLE pe_special_resource_definitions
    ALTER COLUMN base_cap TYPE NUMERIC USING base_cap::numeric;
ALTER TABLE pe_production_chain_definitions
    ALTER COLUMN base_output_per_hour TYPE NUMERIC USING base_output_per_hour::numeric;
