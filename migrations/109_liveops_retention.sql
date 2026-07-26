-- EPIC-22 LiveOps Retention — Login calendar + Battle Pass + Premium entitlements

CREATE TABLE IF NOT EXISTS login_reward_progress (
    player_id INTEGER NOT NULL PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL,
    cycle_started_at REAL NOT NULL DEFAULT 0,
    current_day INTEGER NOT NULL DEFAULT 0 CHECK (current_day >= 0 AND current_day <= 30),
    last_claim_day_bucket INTEGER,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS login_reward_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    cycle_id TEXT NOT NULL,
    day_index INTEGER NOT NULL CHECK (day_index >= 1 AND day_index <= 30),
    reward_json TEXT NOT NULL DEFAULT '{}',
    claimed_at REAL NOT NULL DEFAULT 0,
    UNIQUE (player_id, cycle_id, day_index)
);

CREATE INDEX IF NOT EXISTS idx_login_reward_claims_player
    ON login_reward_claims (player_id, claimed_at DESC);

CREATE TABLE IF NOT EXISTS battle_pass_seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    title_key TEXT NOT NULL DEFAULT 'bp_season_default_title',
    starts_at REAL NOT NULL DEFAULT 0,
    ends_at REAL NOT NULL DEFAULT 0,
    xp_per_level INTEGER NOT NULL DEFAULT 100 CHECK (xp_per_level > 0),
    max_level INTEGER NOT NULL DEFAULT 50 CHECK (max_level > 0),
    active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
    created_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS battle_pass_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER NOT NULL REFERENCES battle_pass_seasons(id) ON DELETE CASCADE,
    level INTEGER NOT NULL CHECK (level >= 1),
    free_reward_json TEXT NOT NULL DEFAULT '{}',
    premium_reward_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (season_id, level)
);

CREATE INDEX IF NOT EXISTS idx_battle_pass_levels_season
    ON battle_pass_levels (season_id, level);

CREATE TABLE IF NOT EXISTS player_battle_pass (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    season_id INTEGER NOT NULL REFERENCES battle_pass_seasons(id) ON DELETE CASCADE,
    xp INTEGER NOT NULL DEFAULT 0 CHECK (xp >= 0),
    level INTEGER NOT NULL DEFAULT 0 CHECK (level >= 0),
    premium_unlocked INTEGER NOT NULL DEFAULT 0 CHECK (premium_unlocked IN (0, 1)),
    premium_unlocked_at REAL,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, season_id)
);

CREATE TABLE IF NOT EXISTS battle_pass_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    season_id INTEGER NOT NULL REFERENCES battle_pass_seasons(id) ON DELETE CASCADE,
    level INTEGER NOT NULL CHECK (level >= 1),
    track TEXT NOT NULL CHECK (track IN ('free', 'premium')),
    reward_json TEXT NOT NULL DEFAULT '{}',
    claimed_at REAL NOT NULL DEFAULT 0,
    UNIQUE (player_id, season_id, level, track)
);

CREATE INDEX IF NOT EXISTS idx_battle_pass_claims_player
    ON battle_pass_claims (player_id, season_id);

CREATE TABLE IF NOT EXISTS premium_entitlements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    season_id INTEGER REFERENCES battle_pass_seasons(id) ON DELETE SET NULL,
    source TEXT NOT NULL DEFAULT 'admin',
    granted_at REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, kind, season_id)
);

CREATE INDEX IF NOT EXISTS idx_premium_entitlements_player
    ON premium_entitlements (player_id, kind);
