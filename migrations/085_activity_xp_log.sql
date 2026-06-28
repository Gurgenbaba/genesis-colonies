-- 085_activity_xp_log.sql
-- Activity XP audit log (bridge to future account/battlepass XP).

CREATE TABLE IF NOT EXISTS activity_xp_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    source_key TEXT NOT NULL,
    amount INTEGER NOT NULL,
    metadata_json TEXT,
    idempotency_key TEXT,
    day_bucket INTEGER NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (player_id) REFERENCES users(id),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_activity_xp_idempotency
    ON activity_xp_log(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_activity_xp_player_day_source
    ON activity_xp_log(player_id, day_bucket, source_key);

CREATE INDEX IF NOT EXISTS idx_activity_xp_planet_day
    ON activity_xp_log(planet_id, day_bucket);
