-- GC-PG-HIGHSPEED-001C: isolate hot online-presence writes from players gameplay rows.
-- Intentionally no FK: PostgreSQL FK checks can take a KEY SHARE lock on players,
-- which would put authenticated presence back onto the gameplay-row lock graph.
CREATE TABLE IF NOT EXISTS player_presence (
    player_id BIGINT PRIMARY KEY,
    last_seen BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_player_presence_last_seen
    ON player_presence(last_seen);

-- Non-destructive compatibility backfill. Legacy players.last_seen remains in place
-- while readers migrate; existing dedicated rows always win on repeat migrations.
INSERT INTO player_presence (player_id, last_seen, updated_at)
SELECT id,
       CAST(COALESCE(last_seen, 0) AS BIGINT),
       CAST(COALESCE(last_seen, 0) AS BIGINT)
FROM players
ON CONFLICT (player_id) DO NOTHING;
