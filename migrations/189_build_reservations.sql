-- GC-RESERVE-001 - "reserve next purchase" for the building queue (phase 1, buildings only).
-- A reservation is an INTENT that holds no resources: this migration charges, grants and queues nothing and
-- changes no existing row. The feature itself is off unless GC_RESERVE_NEXT_PURCHASE is set (default: off).
--
-- Guarantees that hold even if application code is wrong:
--   * at most ONE armed reservation per planet (partial unique index),
--   * the same client request id is one reservation (partial unique index),
--   * a build job belongs to at most one reservation (partial unique index on job_id).
-- The charge happens later, inside the normal build transaction, when the reservation is claimed
-- (armed -> started, compare-and-swap) together with the debit and the job insert.
CREATE TABLE IF NOT EXISTS build_reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    expected_level INTEGER NOT NULL,
    state TEXT NOT NULL DEFAULT 'armed' CHECK (state IN ('armed', 'started', 'cancelled', 'expired')),
    reason TEXT,
    request_id TEXT,
    est_cost_metal TEXT NOT NULL DEFAULT '0',
    est_cost_crystal TEXT NOT NULL DEFAULT '0',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    ended_at REAL,
    job_id INTEGER,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_build_reservations_one_armed_per_planet
    ON build_reservations (planet_id)
    WHERE state = 'armed';

CREATE UNIQUE INDEX IF NOT EXISTS ux_build_reservations_request
    ON build_reservations (player_id, request_id)
    WHERE request_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_build_reservations_job
    ON build_reservations (job_id)
    WHERE job_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_build_reservations_player_state
    ON build_reservations (player_id, state);

CREATE INDEX IF NOT EXISTS idx_build_reservations_ended
    ON build_reservations (ended_at)
    WHERE state <> 'armed';
