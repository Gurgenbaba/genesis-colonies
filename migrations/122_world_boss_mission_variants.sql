-- GC-WB-TAME: mission variants + success/fail outcome
ALTER TABLE player_boss_missions ADD COLUMN variant_key TEXT;
ALTER TABLE player_boss_missions ADD COLUMN fail_chance REAL NOT NULL DEFAULT 0;
ALTER TABLE player_boss_missions ADD COLUMN outcome TEXT;
