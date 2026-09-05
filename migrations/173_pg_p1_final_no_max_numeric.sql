-- 173_pg_p1_final_no_max_numeric.sql
-- GC-BACKEND: postgres
-- Final no-max cleanup for gameplay quantities that were previously widened
-- from int4 to BIGINT as an operational floor. Genesis Colonies has no
-- gameplay ceiling for these stock/value domains, so the canonical PG type is
-- unconstrained NUMERIC.

ALTER TABLE defense_queue
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;

ALTER TABLE planet_troops
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;

ALTER TABLE troop_queue
    ALTER COLUMN amount TYPE NUMERIC USING amount::numeric;

ALTER TABLE expedition_daily_value
    ALTER COLUMN expo_value_total TYPE NUMERIC USING expo_value_total::numeric;

ALTER TABLE expedition_daily_recorded
    ALTER COLUMN expo_value TYPE NUMERIC USING expo_value::numeric;

ALTER TABLE pirate_intel
    ALTER COLUMN resources_score TYPE NUMERIC USING resources_score::numeric;
ALTER TABLE pirate_intel
    ALTER COLUMN fleet_score TYPE NUMERIC USING fleet_score::numeric;
ALTER TABLE pirate_intel
    ALTER COLUMN defense_score TYPE NUMERIC USING defense_score::numeric;

ALTER TABLE chronicle_entries
    ALTER COLUMN score_value TYPE NUMERIC USING score_value::numeric;

ALTER TABLE planet_shipyard_ascension
    ALTER COLUMN hull_mass_progress TYPE NUMERIC USING hull_mass_progress::numeric;
