-- 006_add_player_scores.sql
-- Safe: keine Referenz auf build_queue/building_type

-- players: banned_until
ALTER TABLE players ADD COLUMN banned_until INTEGER;

-- planets: player_id
ALTER TABLE planets ADD COLUMN player_id INTEGER;

-- player_scores: Ranking-Tabelle
CREATE TABLE IF NOT EXISTS player_scores (
    player_id        INTEGER PRIMARY KEY,
    score_total      INTEGER NOT NULL DEFAULT 0,
    score_buildings  INTEGER NOT NULL DEFAULT 0,
    score_research   INTEGER NOT NULL DEFAULT 0,
    updated_at       INTEGER NOT NULL DEFAULT 0
);

-- Indizes fürs Ranking
CREATE INDEX IF NOT EXISTS idx_player_scores_total
    ON player_scores (score_total DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_player_scores_updated
    ON player_scores (updated_at DESC);
