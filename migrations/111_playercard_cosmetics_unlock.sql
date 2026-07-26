-- Season Pass cosmetics: unlockable season themes + BP-only badges.
-- Base themes (cyan/violet/amber/emerald/rose) stay free — never gated.

CREATE TABLE IF NOT EXISTS player_card_unlocked_themes (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    theme_key TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'battle_pass',
    PRIMARY KEY (player_id, theme_key)
);

CREATE INDEX IF NOT EXISTS idx_pc_unlocked_themes_player
    ON player_card_unlocked_themes (player_id, unlocked_at DESC);

-- Season badges: no score requirement → only manual / battle-pass unlock.
INSERT OR IGNORE INTO player_card_badges
    (badge_key, icon, rarity, name_i18n_key, description_i18n_key,
     requirement_type, requirement_value, is_active)
VALUES
    ('bp_s1_attendee', '', 'common', 'playercard_badge_bp_s1_attendee', 'playercard_badge_bp_s1_attendee_desc', NULL, NULL, 1),
    ('bp_s1_operative', '', 'rare', 'playercard_badge_bp_s1_operative', 'playercard_badge_bp_s1_operative_desc', NULL, NULL, 1),
    ('bp_s1_elite', '', 'epic', 'playercard_badge_bp_s1_elite', 'playercard_badge_bp_s1_elite_desc', NULL, NULL, 1),
    ('bp_s1_legend', '', 'legendary', 'playercard_badge_bp_s1_legend', 'playercard_badge_bp_s1_legend_desc', NULL, NULL, 1);
