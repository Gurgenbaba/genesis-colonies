-- 095_score_resources.sql
-- GC-SCORE-B: persist warehouse resource score component separately from assets.

ALTER TABLE player_scores ADD COLUMN score_resources INTEGER NOT NULL DEFAULT 0;
