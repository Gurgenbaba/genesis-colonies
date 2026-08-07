-- 145_imperial_mandates.sql
-- Late-game colony capacity: legacy PE extrapolation credit + mandate entitlements.
-- Admin ceiling default 9 → 11 (only when still at old default).

ALTER TABLE players ADD COLUMN expansion_legacy_slots INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN expansion_legacy_migrated INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS player_imperial_mandates (
    player_id INTEGER NOT NULL,
    mandate_key TEXT NOT NULL,
    earned_at REAL NOT NULL,
    PRIMARY KEY (player_id, mandate_key)
);

CREATE INDEX IF NOT EXISTS idx_player_imperial_mandates_player
    ON player_imperial_mandates (player_id);

UPDATE game_settings
SET value = '11'
WHERE key = 'max_colonies_per_player' AND CAST(value AS INTEGER) IN (9, 10);
