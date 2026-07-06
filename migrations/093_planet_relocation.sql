-- Planet relocation (evacuation move to free galaxy slot)

CREATE TABLE IF NOT EXISTS planet_relocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    from_galaxy INTEGER NOT NULL,
    from_system INTEGER NOT NULL,
    from_position INTEGER NOT NULL,
    target_galaxy INTEGER NOT NULL,
    target_system INTEGER NOT NULL,
    target_position INTEGER NOT NULL,
    started_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_planet_relocations_active_planet
    ON planet_relocations(planet_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_planet_relocations_finish
    ON planet_relocations(status, finish_at);

ALTER TABLE planets ADD COLUMN relocation_cooldown_until REAL;
