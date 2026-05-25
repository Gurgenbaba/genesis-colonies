-- 009_legacy_planets_hardening.sql
-- Upgrade legacy planets rows missing player_id / is_homeworld (pre-006 / partial 006 DBs).

ALTER TABLE planets ADD COLUMN player_id INTEGER;
ALTER TABLE planets ADD COLUMN is_homeworld INTEGER NOT NULL DEFAULT 0;

UPDATE planets SET player_id = 1 WHERE player_id IS NULL;

UPDATE planets
SET is_homeworld = 1
WHERE id IN (
    SELECT p1.id
    FROM planets p1
    INNER JOIN (
        SELECT player_id, MIN(id) AS min_id
        FROM planets
        GROUP BY player_id
    ) t ON t.min_id = p1.id
    WHERE NOT EXISTS (
        SELECT 1
        FROM planets p2
        WHERE p2.player_id = p1.player_id
          AND p2.is_homeworld = 1
    )
);

CREATE INDEX IF NOT EXISTS idx_planets_player_id ON planets (player_id);
CREATE INDEX IF NOT EXISTS idx_planets_player_homeworld ON planets (player_id, is_homeworld);
