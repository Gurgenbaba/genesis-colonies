-- EPIC-22 Season Ops — daily/weekly battle-pass challenges (XP only, no inventory grants)

CREATE TABLE IF NOT EXISTS battle_pass_ops_progress (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    season_id INTEGER NOT NULL REFERENCES battle_pass_seasons(id) ON DELETE CASCADE,
    period_key TEXT NOT NULL,
    op_key TEXT NOT NULL,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress >= 0),
    target INTEGER NOT NULL DEFAULT 1 CHECK (target > 0),
    xp_reward INTEGER NOT NULL DEFAULT 0 CHECK (xp_reward >= 0),
    claimed_at REAL,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, season_id, period_key, op_key)
);

CREATE INDEX IF NOT EXISTS idx_battle_pass_ops_player_period
    ON battle_pass_ops_progress (player_id, season_id, period_key);
