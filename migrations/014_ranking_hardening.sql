-- 014_ranking_hardening.sql
-- Extends player_scores for fleet/defense (future) and cached rank columns.
-- Backward-compatible: existing rows keep score_total/buildings/research.

ALTER TABLE player_scores ADD COLUMN score_fleet INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN score_defense INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN rank_total INTEGER;
ALTER TABLE player_scores ADD COLUMN rank_building INTEGER;
ALTER TABLE player_scores ADD COLUMN rank_research INTEGER;

CREATE INDEX IF NOT EXISTS idx_player_scores_rank_total
    ON player_scores (rank_total ASC);
