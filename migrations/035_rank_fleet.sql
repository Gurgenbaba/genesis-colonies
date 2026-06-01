-- 035_rank_fleet.sql
-- Cached fleet rank column (consistent with rank_building / rank_research).

ALTER TABLE player_scores ADD COLUMN rank_fleet INTEGER;

CREATE INDEX IF NOT EXISTS idx_player_scores_rank_fleet
    ON player_scores (rank_fleet ASC);
