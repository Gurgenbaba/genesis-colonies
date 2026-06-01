-- 040_defense_queue.sql
-- Planet-scoped defense build queue (GC-411).

CREATE TABLE IF NOT EXISTS defense_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    defense_key TEXT NOT NULL,
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

CREATE INDEX IF NOT EXISTS idx_defense_queue_planet
    ON defense_queue(planet_id);

CREATE INDEX IF NOT EXISTS idx_defense_queue_planet_pos
    ON defense_queue(planet_id, queue_position);

CREATE INDEX IF NOT EXISTS idx_defense_queue_finish
    ON defense_queue(finish_at);
