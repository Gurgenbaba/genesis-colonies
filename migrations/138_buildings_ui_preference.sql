-- 138_buildings_ui_preference.sql
-- Account preference: Colony Stage (default) vs Retro building cards.
-- buildings_ui_choice_done=0 → show one-time chooser on next in-game visit.

ALTER TABLE users ADD COLUMN buildings_ui_mode TEXT NOT NULL DEFAULT 'stage';
ALTER TABLE users ADD COLUMN buildings_ui_choice_done INTEGER NOT NULL DEFAULT 0;
