-- GC-PG-HIGHSPEED-001C: isolate hot online-presence writes from players gameplay rows.
-- Intentionally no FK: PostgreSQL FK checks can take a KEY SHARE lock on players,
-- which would put authenticated presence back onto the gameplay-row lock graph.
--
-- No eager SELECT from players here: historical migration fixtures intentionally
-- exercise partial schemas that may not contain players. Existing players.last_seen
-- remains untouched and is the reader fallback until each account is lazily seeded
-- by its first dedicated presence UPSERT.
CREATE TABLE IF NOT EXISTS player_presence (
    player_id BIGINT PRIMARY KEY,
    last_seen BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_player_presence_last_seen
    ON player_presence(last_seen);
