-- 030_shipyard_queue_positions.sql
-- Queue ordering, stored build costs (cancel refund), and active-job support.

ALTER TABLE shipyard_queue ADD COLUMN queue_position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shipyard_queue ADD COLUMN cost_metal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shipyard_queue ADD COLUMN cost_crystal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shipyard_queue ADD COLUMN cost_fuel_cells REAL NOT NULL DEFAULT 0;

UPDATE shipyard_queue
SET queue_position = id
WHERE queue_position = 0 AND status = 'queued';

CREATE INDEX IF NOT EXISTS idx_shipyard_queue_planet_pos
    ON shipyard_queue(planet_id, queue_position);
