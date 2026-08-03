-- 129_sfx_sound_options.sql
-- UI SFX (lootbox, titan click, …) + combat theater SFX: off | quiet | normal

ALTER TABLE users ADD COLUMN sfx_ui_sound TEXT NOT NULL DEFAULT 'normal';
ALTER TABLE users ADD COLUMN sfx_combat_sound TEXT NOT NULL DEFAULT 'normal';
