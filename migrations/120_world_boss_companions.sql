-- GC-WB-TAME: tamed World Boss companions + catch CD + Ark-Token missions

CREATE TABLE IF NOT EXISTS player_boss_companions (
    player_id INTEGER NOT NULL,
    boss_key TEXT NOT NULL,
    tamed_at REAL NOT NULL,
    tamed_event_id INTEGER,
    PRIMARY KEY (player_id, boss_key)
);

CREATE INDEX IF NOT EXISTS idx_player_boss_companions_player
    ON player_boss_companions (player_id);

CREATE TABLE IF NOT EXISTS player_boss_catch_state (
    player_id INTEGER NOT NULL,
    boss_key TEXT NOT NULL,
    last_catch_at REAL,
    cooldown_until REAL NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, boss_key)
);

CREATE TABLE IF NOT EXISTS player_boss_missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    boss_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idle',
    started_at REAL,
    ends_at REAL,
    reward_tokens INTEGER NOT NULL DEFAULT 0,
    request_id TEXT,
    updated_at REAL NOT NULL,
    UNIQUE (player_id, boss_key)
);

CREATE INDEX IF NOT EXISTS idx_player_boss_missions_status_ends
    ON player_boss_missions (status, ends_at);
