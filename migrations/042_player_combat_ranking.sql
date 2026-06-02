-- 042_player_combat_ranking.sql
-- Combat destruction tracking for military ranking (GC-509).

ALTER TABLE player_scores ADD COLUMN score_destroyed_raw INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN score_combat INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN score_destroyed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN rank_combat INTEGER;
ALTER TABLE player_scores ADD COLUMN rank_destroyed INTEGER;
ALTER TABLE player_scores ADD COLUMN rank_military INTEGER;
