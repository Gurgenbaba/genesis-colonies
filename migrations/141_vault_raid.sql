-- 141_vault_raid.sql
-- Secret Vault Raid: planet troop stock/queue + attack troop cargo.

CREATE TABLE IF NOT EXISTS planet_troops (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    troop_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0 CHECK(amount >= 0),
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    UNIQUE(planet_id, troop_key)
);

CREATE INDEX IF NOT EXISTS idx_planet_troops_planet
    ON planet_troops(planet_id);

CREATE TABLE IF NOT EXISTS troop_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    troop_key TEXT NOT NULL,
    amount INTEGER NOT NULL CHECK(amount > 0),
    status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'completed', 'cancelled')),
    started_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    created_at REAL NOT NULL,
    queue_position INTEGER NOT NULL DEFAULT 0,
    cost_metal INTEGER NOT NULL DEFAULT 0,
    cost_crystal INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_troop_queue_planet
    ON troop_queue(planet_id);

CREATE INDEX IF NOT EXISTS idx_troop_queue_planet_pos
    ON troop_queue(planet_id, queue_position);

CREATE INDEX IF NOT EXISTS idx_troop_queue_finish
    ON troop_queue(finish_at);

-- Attack troop cargo (empty object when none).
ALTER TABLE fleet_movements ADD COLUMN troops_json TEXT NOT NULL DEFAULT '{}';
