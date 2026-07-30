-- GC-PERF-BOOST-001 — Tier stacking: one row per (user, effect_key, source_item_key)
-- Same item extends duration; different % tiers coexist; EffectResolver keeps max(mult).

CREATE TABLE IF NOT EXISTS player_active_boosters__tier (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    effect_key TEXT NOT NULL,
    multiplier REAL NOT NULL DEFAULT 1.0,
    expires_at REAL NOT NULL,
    source_item_key TEXT NOT NULL DEFAULT '',
    activated_at REAL NOT NULL,
    UNIQUE(user_id, effect_key, source_item_key)
);

INSERT OR IGNORE INTO player_active_boosters__tier (
    id, user_id, effect_key, multiplier, expires_at, source_item_key, activated_at
)
SELECT
    id,
    user_id,
    effect_key,
    multiplier,
    expires_at,
    COALESCE(NULLIF(TRIM(source_item_key), ''), effect_key),
    activated_at
FROM player_active_boosters;

DROP TABLE IF EXISTS player_active_boosters;
ALTER TABLE player_active_boosters__tier RENAME TO player_active_boosters;

CREATE INDEX IF NOT EXISTS idx_player_active_boosters_user_expires
    ON player_active_boosters(user_id, expires_at);
