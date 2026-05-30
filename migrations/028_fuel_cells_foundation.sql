-- 028_fuel_cells_foundation.sql
-- Fuel cells resource, fuel cell plant building, shipyard queue scaffold.

ALTER TABLE planets ADD COLUMN fuel_cells REAL NOT NULL DEFAULT 500 CHECK(fuel_cells >= 0);

UPDATE planets SET fuel_cells = 500 WHERE fuel_cells IS NULL OR fuel_cells < 0;

ALTER TABLE planet_buildings ADD COLUMN fuel_cell_plant INTEGER DEFAULT 0 CHECK(fuel_cell_plant >= 0);

CREATE TABLE IF NOT EXISTS shipyard_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    ship_key TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'completed', 'cancelled')),
    started_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_shipyard_queue_planet ON shipyard_queue(planet_id);
CREATE INDEX IF NOT EXISTS idx_shipyard_queue_player ON shipyard_queue(player_id);
CREATE INDEX IF NOT EXISTS idx_shipyard_queue_finish ON shipyard_queue(finish_at);
