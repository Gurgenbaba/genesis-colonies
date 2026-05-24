-- 007_seed_player_scores.sql
-- Initialisiert player_scores für alle vorhandenen Spieler (idempotent)

INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
SELECT
  p.id AS player_id,
  0    AS score_total,
  0    AS score_buildings,
  0    AS score_research,
  CAST(strftime('%s','now') AS INTEGER) AS updated_at
FROM players p
WHERE NOT EXISTS (
  SELECT 1 FROM player_scores s WHERE s.player_id = p.id
);
