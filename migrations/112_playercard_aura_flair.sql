-- Player card prestige cosmetics: equippable aura + title flair (Season Pass).
-- Base themes remain free; this layer is unlock-gated separately.

ALTER TABLE player_cards ADD COLUMN aura_key TEXT NOT NULL DEFAULT 'none';
ALTER TABLE player_cards ADD COLUMN title_flair TEXT NOT NULL DEFAULT 'none';

CREATE TABLE IF NOT EXISTS player_card_unlocked_cosmetics (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('aura', 'title_flair')),
    item_key TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'battle_pass',
    PRIMARY KEY (player_id, kind, item_key)
);

CREATE INDEX IF NOT EXISTS idx_pc_unlocked_cosmetics_player
    ON player_card_unlocked_cosmetics (player_id, kind, unlocked_at DESC);
