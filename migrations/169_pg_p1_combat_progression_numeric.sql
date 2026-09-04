-- 169_pg_p1_combat_progression_numeric.sql
-- GC-BACKEND: postgres
-- P1-A: no-max combat/progression counters become unconstrained NUMERIC.
-- These values can grow with boss tuning, combat scale and persistent progress;
-- BIGINT would only move the cap rather than remove it.

ALTER TABLE world_boss_definitions
    ALTER COLUMN max_hp TYPE NUMERIC USING max_hp::numeric;

ALTER TABLE world_boss_events
    ALTER COLUMN max_hp TYPE NUMERIC USING max_hp::numeric;
ALTER TABLE world_boss_events
    ALTER COLUMN current_hp TYPE NUMERIC USING current_hp::numeric;

ALTER TABLE world_boss_contributions
    ALTER COLUMN damage TYPE NUMERIC USING damage::numeric;

ALTER TABLE pirate_bases
    ALTER COLUMN max_hp TYPE NUMERIC USING max_hp::numeric;
ALTER TABLE pirate_bases
    ALTER COLUMN current_hp TYPE NUMERIC USING current_hp::numeric;

ALTER TABLE pirate_base_contributions
    ALTER COLUMN damage TYPE NUMERIC USING damage::numeric;

ALTER TABLE combat_hall_of_fame
    ALTER COLUMN attacker_loss_score TYPE NUMERIC USING attacker_loss_score::numeric;
ALTER TABLE combat_hall_of_fame
    ALTER COLUMN defender_loss_score TYPE NUMERIC USING defender_loss_score::numeric;
ALTER TABLE combat_hall_of_fame
    ALTER COLUMN total_destroyed_score TYPE NUMERIC USING total_destroyed_score::numeric;

ALTER TABLE player_directives
    ALTER COLUMN target_value TYPE NUMERIC USING target_value::numeric;
ALTER TABLE player_directives
    ALTER COLUMN progress_value TYPE NUMERIC USING progress_value::numeric;

ALTER TABLE directive_progress
    ALTER COLUMN delta TYPE NUMERIC USING delta::numeric;

ALTER TABLE case_battles
    ALTER COLUMN total_battle_value TYPE NUMERIC USING total_battle_value::numeric;

ALTER TABLE case_battle_rolls
    ALTER COLUMN reward_amount TYPE NUMERIC USING reward_amount::numeric;
ALTER TABLE case_battle_rolls
    ALTER COLUMN reward_value TYPE NUMERIC USING reward_value::numeric;
