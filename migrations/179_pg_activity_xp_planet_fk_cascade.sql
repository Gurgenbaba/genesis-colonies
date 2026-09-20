-- 179_pg_activity_xp_planet_fk_cascade.sql
-- GC-BACKEND: postgres
-- UNI1 prelaunch reset: activity_xp_log historically referenced planets
-- without ON DELETE CASCADE, so deleting reset planets could fail after
-- activity XP had been written.

ALTER TABLE activity_xp_log
    DROP CONSTRAINT IF EXISTS activity_xp_log_planet_id_fkey;

ALTER TABLE activity_xp_log
    ADD CONSTRAINT activity_xp_log_planet_id_fkey
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE;
