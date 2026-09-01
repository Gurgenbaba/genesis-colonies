-- GC-PG-HIGHSPEED-001D: additive indexes for current production hot paths.
-- GC-REQUIRES-TABLES: world_boss_events, shipyard_queue
--
-- The precondition keeps historical partial-schema migration fixtures safe.
-- Production has both modules installed, so this migration applies once there.

CREATE INDEX IF NOT EXISTS idx_world_boss_events_status_window_id
    ON world_boss_events(status, ends_at, starts_at, id);

CREATE INDEX IF NOT EXISTS idx_world_boss_events_status_updated
    ON world_boss_events(status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_shipyard_queue_planet_status_pos_id
    ON shipyard_queue(planet_id, status, queue_position, id);

CREATE INDEX IF NOT EXISTS idx_shipyard_queue_status_finish_planet
    ON shipyard_queue(status, finish_at, planet_id);
