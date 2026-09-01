-- GC-PG-HIGHSPEED-001E: isolate active planet context writes from the hot players row.
-- GC-REQUIRES-TABLES: users, players, planets
--
-- Ownership references users (cold account row), not players (hot gameplay row).
-- active_planet_id is validated in application code to avoid adding a lock edge
-- from every context switch to the hot planets resource row.
CREATE TABLE IF NOT EXISTS player_context (
    player_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    active_planet_id BIGINT,
    updated_at BIGINT NOT NULL DEFAULT 0
);

INSERT INTO player_context (player_id, active_planet_id, updated_at)
SELECT p.id, p.active_planet_id, 0
FROM players p
JOIN users u ON u.id = p.id
WHERE p.active_planet_id IS NOT NULL
  AND EXISTS (
      SELECT 1
      FROM planets pl
      WHERE pl.id = p.active_planet_id
        AND pl.player_id = p.id
  )
ON CONFLICT (player_id) DO NOTHING;
