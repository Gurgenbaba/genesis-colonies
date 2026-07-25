-- EPIC-20: track alliance XP earned per world-boss contribution
ALTER TABLE world_boss_contributions ADD COLUMN alliance_xp INTEGER NOT NULL DEFAULT 0;
