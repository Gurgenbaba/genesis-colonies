-- GC-968A — Active inventory boosters (timed EffectResolver modifiers)

CREATE TABLE IF NOT EXISTS player_active_boosters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    effect_key TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    expires_at REAL NOT NULL,
    source_item_key TEXT,
    activated_at REAL NOT NULL,
    UNIQUE(user_id, effect_key)
);

CREATE INDEX IF NOT EXISTS idx_player_active_boosters_user_expires
    ON player_active_boosters(user_id, expires_at);
