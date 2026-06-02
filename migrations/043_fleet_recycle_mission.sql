-- 043_fleet_recycle_mission.sql
-- GC-800: recycle mission on fleet_movements / fleet_presets (SQLite CHECK rebuild).

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS fleet_movements_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    origin_planet_id INTEGER NOT NULL,
    target_planet_id INTEGER,
    target_galaxy INTEGER NOT NULL,
    target_system INTEGER NOT NULL,
    target_position INTEGER NOT NULL,
    mission_type TEXT NOT NULL CHECK(mission_type IN (
        'transport', 'collect', 'deploy', 'spy', 'attack', 'hold', 'expedition', 'colonize', 'recycle'
    )),
    status TEXT NOT NULL CHECK(status IN (
        'outbound', 'holding', 'returning', 'completed', 'cancelled', 'failed'
    )),
    departure_at REAL NOT NULL,
    arrival_at REAL NOT NULL,
    return_at REAL,
    holding_until REAL,
    ships_json TEXT NOT NULL,
    resources_json TEXT NOT NULL DEFAULT '{}',
    fuel_cost REAL NOT NULL DEFAULT 0,
    speed_percent INTEGER NOT NULL DEFAULT 100 CHECK(speed_percent >= 10 AND speed_percent <= 100),
    distance INTEGER NOT NULL DEFAULT 0,
    flight_seconds INTEGER NOT NULL DEFAULT 0,
    preset_id INTEGER,
    parent_batch_id INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(origin_planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    FOREIGN KEY(target_planet_id) REFERENCES planets(id) ON DELETE SET NULL,
    FOREIGN KEY(preset_id) REFERENCES fleet_presets(id) ON DELETE SET NULL,
    FOREIGN KEY(parent_batch_id) REFERENCES fleet_batches(id) ON DELETE SET NULL
);

INSERT INTO fleet_movements_new
SELECT * FROM fleet_movements;

DROP TABLE fleet_movements;

ALTER TABLE fleet_movements_new RENAME TO fleet_movements;

CREATE INDEX IF NOT EXISTS idx_fleet_movements_player_status
    ON fleet_movements(player_id, status);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_arrival
    ON fleet_movements(status, arrival_at);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_return
    ON fleet_movements(status, return_at);

CREATE TABLE IF NOT EXISTS fleet_presets_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    preset_type TEXT NOT NULL DEFAULT 'custom' CHECK(preset_type IN (
        'raid', 'farm', 'spy', 'transport', 'deploy', 'expedition', 'custom'
    )),
    ships_json TEXT NOT NULL DEFAULT '{}',
    resources_json TEXT NOT NULL DEFAULT '{}',
    speed_percent INTEGER NOT NULL DEFAULT 100 CHECK(speed_percent >= 10 AND speed_percent <= 100),
    mission_type TEXT CHECK(mission_type IS NULL OR mission_type IN (
        'transport', 'collect', 'deploy', 'spy', 'attack', 'hold', 'expedition', 'colonize', 'recycle'
    )),
    target_galaxy INTEGER,
    target_system INTEGER,
    target_position INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

INSERT INTO fleet_presets_new
SELECT * FROM fleet_presets;

DROP TABLE fleet_presets;

ALTER TABLE fleet_presets_new RENAME TO fleet_presets;

CREATE INDEX IF NOT EXISTS idx_fleet_presets_player
    ON fleet_presets(player_id);

PRAGMA foreign_keys = ON;
