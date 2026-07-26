-- GC Identity Cosmetics: equippable name_style + shop kind cosmetic_unlock.
-- Expands unlock kinds and shop product kinds (CHECK rebuild).

ALTER TABLE player_cards ADD COLUMN name_style TEXT NOT NULL DEFAULT 'none';

-- Rebuild unlocked cosmetics to allow kind=name_style
CREATE TABLE IF NOT EXISTS player_card_unlocked_cosmetics__ns (
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('aura', 'title_flair', 'name_style')),
    item_key TEXT NOT NULL,
    unlocked_at INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'battle_pass',
    PRIMARY KEY (player_id, kind, item_key)
);

INSERT OR IGNORE INTO player_card_unlocked_cosmetics__ns
    (player_id, kind, item_key, unlocked_at, source)
SELECT player_id, kind, item_key, unlocked_at, source
FROM player_card_unlocked_cosmetics;

DROP TABLE IF EXISTS player_card_unlocked_cosmetics;
ALTER TABLE player_card_unlocked_cosmetics__ns RENAME TO player_card_unlocked_cosmetics;

CREATE INDEX IF NOT EXISTS idx_pc_unlocked_cosmetics_player
    ON player_card_unlocked_cosmetics (player_id, kind, unlocked_at DESC);

-- Rebuild shop_products to allow kind=cosmetic_unlock
CREATE TABLE IF NOT EXISTS shop_products__ns (
    sku TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('entitlement', 'timekeeper', 'inventory_bundle', 'cosmetic_unlock')),
    title_key TEXT NOT NULL DEFAULT '',
    hint_key TEXT NOT NULL DEFAULT '',
    price_cents INTEGER NOT NULL CHECK (price_cents > 0),
    currency TEXT NOT NULL DEFAULT 'eur',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    payload_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

INSERT OR IGNORE INTO shop_products__ns
    (sku, kind, title_key, hint_key, price_cents, currency, active, payload_json, sort_order, created_at, updated_at)
SELECT sku, kind, title_key, hint_key, price_cents, currency, active, payload_json, sort_order, created_at, updated_at
FROM shop_products;

DROP TABLE IF EXISTS shop_products;
ALTER TABLE shop_products__ns RENAME TO shop_products;
