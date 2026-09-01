-- GC-PG-HIGHSPEED-001D: one-time history handoff before removing the
-- PostgreSQL compatibility fallback to players.last_seen.
-- GC-REQUIRES-TABLES: users, players, player_presence
--
-- Keep the newest timestamp when a canonical row already exists. This covers
-- rolling deployments where player_presence has already advanced past the
-- legacy mirror, while still rescuing dormant accounts that never received a
-- canonical presence row after migration 158.

UPDATE player_presence
SET last_seen = (
        SELECT COALESCE(p.last_seen, 0)
        FROM players p
        WHERE p.id = player_presence.player_id
    ),
    updated_at = CASE
        WHEN COALESCE(player_presence.updated_at, 0) > (
            SELECT COALESCE(p.last_seen, 0)
            FROM players p
            WHERE p.id = player_presence.player_id
        )
        THEN player_presence.updated_at
        ELSE (
            SELECT COALESCE(p.last_seen, 0)
            FROM players p
            WHERE p.id = player_presence.player_id
        )
    END
WHERE EXISTS (
    SELECT 1
    FROM players p
    WHERE p.id = player_presence.player_id
      AND COALESCE(p.last_seen, 0) > COALESCE(player_presence.last_seen, 0)
);

INSERT INTO player_presence (player_id, last_seen, updated_at)
SELECT p.id,
       COALESCE(p.last_seen, 0),
       COALESCE(p.last_seen, 0)
FROM players p
JOIN users u ON u.id = p.id
WHERE COALESCE(p.last_seen, 0) > 0
  AND NOT EXISTS (
      SELECT 1
      FROM player_presence pp
      WHERE pp.player_id = p.id
  )
ON CONFLICT (player_id) DO NOTHING;
