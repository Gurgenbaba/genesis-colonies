-- 130_case_battles.sql
-- GC-CB: Relikt-Arena / Case Battles (inventory escrow + seeded rolls)

CREATE TABLE IF NOT EXISTS case_battles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    visibility TEXT NOT NULL DEFAULT 'public',
    join_code TEXT,
    player_limit INTEGER NOT NULL DEFAULT 2,
    total_battle_value INTEGER NOT NULL DEFAULT 0,
    cases_json TEXT NOT NULL,
    pool_snapshot_json TEXT,
    server_seed_hash TEXT,
    server_seed TEXT,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    FOREIGN KEY(creator_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_case_battles_status_created
    ON case_battles(status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_case_battles_join_code
    ON case_battles(join_code);

CREATE INDEX IF NOT EXISTS idx_case_battles_creator
    ON case_battles(creator_id, created_at DESC);

CREATE TABLE IF NOT EXISTS case_battle_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    joined_at REAL NOT NULL,
    FOREIGN KEY(battle_id) REFERENCES case_battles(id),
    FOREIGN KEY(user_id) REFERENCES players(id),
    UNIQUE(battle_id, user_id),
    UNIQUE(battle_id, slot)
);

CREATE INDEX IF NOT EXISTS idx_case_battle_players_user
    ON case_battle_players(user_id, joined_at DESC);

CREATE TABLE IF NOT EXISTS case_battle_rolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    battle_id INTEGER NOT NULL,
    round_index INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    container_key TEXT NOT NULL,
    roll_nonce TEXT NOT NULL,
    reward_type TEXT NOT NULL,
    reward_key TEXT NOT NULL,
    reward_amount INTEGER NOT NULL,
    reward_snapshot_json TEXT NOT NULL,
    reward_value INTEGER NOT NULL,
    roll_preview_json TEXT,
    winning_index INTEGER,
    FOREIGN KEY(battle_id) REFERENCES case_battles(id),
    FOREIGN KEY(user_id) REFERENCES players(id),
    UNIQUE(battle_id, round_index, user_id)
);

CREATE INDEX IF NOT EXISTS idx_case_battle_rolls_battle
    ON case_battle_rolls(battle_id, round_index, user_id);

CREATE TABLE IF NOT EXISTS case_battle_settlements (
    battle_id INTEGER PRIMARY KEY,
    winner_id INTEGER NOT NULL,
    totals_json TEXT NOT NULL,
    granted_json TEXT NOT NULL,
    settled_at REAL NOT NULL,
    FOREIGN KEY(battle_id) REFERENCES case_battles(id),
    FOREIGN KEY(winner_id) REFERENCES players(id)
);
