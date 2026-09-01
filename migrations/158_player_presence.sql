-- GC-PG-HIGHSPEED-001C: isolate hot online-presence writes from players gameplay rows.
--
-- Ownership intentionally references users, not players. PostgreSQL FK checks may
-- take a KEY SHARE lock on the parent row; users is cold account/auth ownership,
-- while players is the hot gameplay row we are removing from the presence lock graph.
-- ON DELETE CASCADE prevents ownerless presence rows after permanent account deletion.
--
-- No eager SELECT from players here: historical migration fixtures intentionally
-- exercise partial schemas. Existing players.last_seen remains untouched as the
-- temporary compatibility-reader fallback during 001C cutover.
CREATE TABLE IF NOT EXISTS player_presence (
    player_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    last_seen BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_player_presence_last_seen
    ON player_presence(last_seen);
