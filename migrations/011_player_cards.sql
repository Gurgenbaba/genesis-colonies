-- 011_player_cards.sql
-- Global player profile cards (avatars, bio, badges).

CREATE TABLE IF NOT EXISTS player_cards (
    player_id          INTEGER PRIMARY KEY,
    avatar_url         TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL DEFAULT '',
    bio                TEXT NOT NULL DEFAULT '',
    theme              TEXT NOT NULL DEFAULT 'cyan',
    is_public          INTEGER NOT NULL DEFAULT 1,
    selected_badge_1   INTEGER,
    selected_badge_2   INTEGER,
    selected_badge_3   INTEGER,
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_cards_updated ON player_cards(updated_at DESC);

CREATE TABLE IF NOT EXISTS player_card_badges (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    badge_key           TEXT NOT NULL UNIQUE,
    icon                TEXT NOT NULL DEFAULT '★',
    rarity              TEXT NOT NULL DEFAULT 'common',
    name_i18n_key       TEXT NOT NULL,
    description_i18n_key TEXT NOT NULL,
    requirement_type    TEXT,
    requirement_value   INTEGER,
    is_active           INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS player_card_unlocked_badges (
    player_id   INTEGER NOT NULL,
    badge_id    INTEGER NOT NULL,
    unlocked_at INTEGER NOT NULL,
    PRIMARY KEY (player_id, badge_id),
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(badge_id) REFERENCES player_card_badges(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pc_unlocked_player ON player_card_unlocked_badges(player_id, unlocked_at DESC);

-- Seed default badges (idempotent via badge_key)
INSERT OR IGNORE INTO player_card_badges (badge_key, icon, rarity, name_i18n_key, description_i18n_key, requirement_type, requirement_value, is_active)
VALUES
    ('founder', '◆', 'legendary', 'playercard_badge_founder', 'playercard_badge_founder_desc', NULL, NULL, 1),
    ('builder_1k', '⬡', 'common', 'playercard_badge_builder_1k', 'playercard_badge_builder_1k_desc', 'score_buildings', 1000, 1),
    ('builder_10k', '⬢', 'rare', 'playercard_badge_builder_10k', 'playercard_badge_builder_10k_desc', 'score_buildings', 10000, 1),
    ('researcher_1k', '◎', 'common', 'playercard_badge_researcher_1k', 'playercard_badge_researcher_1k_desc', 'score_research', 1000, 1),
    ('researcher_10k', '◉', 'rare', 'playercard_badge_researcher_10k', 'playercard_badge_researcher_10k_desc', 'score_research', 10000, 1),
    ('commander_5k', '★', 'uncommon', 'playercard_badge_commander_5k', 'playercard_badge_commander_5k_desc', 'score_total', 5000, 1),
    ('commander_50k', '✦', 'epic', 'playercard_badge_commander_50k', 'playercard_badge_commander_50k_desc', 'score_total', 50000, 1);
