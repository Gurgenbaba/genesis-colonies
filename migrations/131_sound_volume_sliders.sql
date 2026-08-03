-- 131_sound_volume_sliders.sql
-- Replace discrete sound modes (off|quiet|normal) with continuous 0..1 volume scales.
-- Existing preferences map equivalently: off→0, quiet→0.5, normal→1.
-- New accounts default to 0.1.
-- ADD COLUMN is idempotent (migrate.py skips duplicate-column errors).

ALTER TABLE users ADD COLUMN notify_attack_sound TEXT NOT NULL DEFAULT '0.1';
ALTER TABLE users ADD COLUMN notify_message_sound TEXT NOT NULL DEFAULT '0.1';
ALTER TABLE users ADD COLUMN sfx_ui_sound TEXT NOT NULL DEFAULT '0.1';
ALTER TABLE users ADD COLUMN sfx_combat_sound TEXT NOT NULL DEFAULT '0.1';

UPDATE users SET notify_attack_sound = '0' WHERE notify_attack_sound = 'off';
UPDATE users SET notify_attack_sound = '0.5' WHERE notify_attack_sound = 'quiet';
UPDATE users SET notify_attack_sound = '1' WHERE notify_attack_sound = 'normal';

UPDATE users SET notify_message_sound = '0' WHERE notify_message_sound = 'off';
UPDATE users SET notify_message_sound = '0.5' WHERE notify_message_sound = 'quiet';
UPDATE users SET notify_message_sound = '1' WHERE notify_message_sound = 'normal';

UPDATE users SET sfx_ui_sound = '0' WHERE sfx_ui_sound = 'off';
UPDATE users SET sfx_ui_sound = '0.5' WHERE sfx_ui_sound = 'quiet';
UPDATE users SET sfx_ui_sound = '1' WHERE sfx_ui_sound = 'normal';

UPDATE users SET sfx_combat_sound = '0' WHERE sfx_combat_sound = 'off';
UPDATE users SET sfx_combat_sound = '0.5' WHERE sfx_combat_sound = 'quiet';
UPDATE users SET sfx_combat_sound = '1' WHERE sfx_combat_sound = 'normal';
