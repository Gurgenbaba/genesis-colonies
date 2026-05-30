-- 027_fleet_core.sql
-- Fleet system: ships on planets, movements, presets, batches.

CREATE TABLE IF NOT EXISTS planet_ships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    ship_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0 CHECK(amount >= 0),
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    UNIQUE(planet_id, ship_key)
);

CREATE INDEX IF NOT EXISTS idx_planet_ships_player
    ON planet_ships(player_id);

CREATE INDEX IF NOT EXISTS idx_planet_ships_planet
    ON planet_ships(planet_id);

CREATE TABLE IF NOT EXISTS fleet_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    preset_type TEXT NOT NULL CHECK(preset_type IN (
        'raid', 'farm', 'spy', 'transport', 'deploy', 'expedition', 'custom'
    )),
    ships_json TEXT NOT NULL,
    resources_json TEXT,
    speed_percent INTEGER NOT NULL DEFAULT 100 CHECK(speed_percent >= 10 AND speed_percent <= 100),
    mission_type TEXT CHECK(mission_type IS NULL OR mission_type IN (
        'transport', 'deploy', 'spy', 'attack', 'hold', 'expedition'
    )),
    target_galaxy INTEGER,
    target_system INTEGER,
    target_position INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleet_presets_player
    ON fleet_presets(player_id);

CREATE TABLE IF NOT EXISTS fleet_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    batch_type TEXT NOT NULL CHECK(batch_type IN (
        'mass_expedition', 'distribute_resources', 'collect_resources', 'mass_transport', 'custom'
    )),
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN (
        'pending', 'running', 'completed', 'cancelled', 'failed'
    )),
    total_fleets INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fleet_batches_player
    ON fleet_batches(player_id);

CREATE TABLE IF NOT EXISTS fleet_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    origin_planet_id INTEGER NOT NULL,
    target_planet_id INTEGER,
    target_galaxy INTEGER NOT NULL,
    target_system INTEGER NOT NULL,
    target_position INTEGER NOT NULL,
    mission_type TEXT NOT NULL CHECK(mission_type IN (
        'transport', 'deploy', 'spy', 'attack', 'hold', 'expedition'
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

CREATE INDEX IF NOT EXISTS idx_fleet_movements_player_status
    ON fleet_movements(player_id, status);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_arrival
    ON fleet_movements(status, arrival_at);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_return
    ON fleet_movements(status, return_at);
