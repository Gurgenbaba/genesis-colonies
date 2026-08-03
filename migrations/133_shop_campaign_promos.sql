-- Campaign / event promo codes (discount-only, no creator commission)

-- Rebuild shop_promo_codes: kind + nullable creator_id
CREATE TABLE IF NOT EXISTS shop_promo_codes__campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'creator'
        CHECK (kind IN ('creator', 'campaign')),
    creator_id INTEGER REFERENCES shop_creators(id) ON DELETE CASCADE,
    discount_bps INTEGER NOT NULL DEFAULT 1000 CHECK (discount_bps >= 0 AND discount_bps <= 9000),
    commission_bps INTEGER NOT NULL DEFAULT 0 CHECK (commission_bps >= 0 AND commission_bps <= 5000),
    max_redemptions INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    CHECK (
        (kind = 'creator' AND creator_id IS NOT NULL)
        OR (kind = 'campaign' AND creator_id IS NULL AND commission_bps = 0)
    )
);

INSERT INTO shop_promo_codes__campaign (
    id, code, kind, creator_id, discount_bps, commission_bps,
    max_redemptions, active, notes, created_at, updated_at
)
SELECT
    id, code, 'creator', creator_id, discount_bps, commission_bps,
    max_redemptions, active, notes, created_at, updated_at
FROM shop_promo_codes;

DROP TABLE shop_promo_codes;
ALTER TABLE shop_promo_codes__campaign RENAME TO shop_promo_codes;

CREATE INDEX IF NOT EXISTS idx_shop_promo_codes_creator
    ON shop_promo_codes (creator_id, active);
CREATE INDEX IF NOT EXISTS idx_shop_promo_codes_kind
    ON shop_promo_codes (kind, active);

-- Allow campaign funnel events without creator
CREATE TABLE IF NOT EXISTS shop_promo_events__campaign (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER REFERENCES shop_creators(id) ON DELETE CASCADE,
    promo_code_id INTEGER REFERENCES shop_promo_codes(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL
        CHECK (event_type IN (
            'click', 'register', 'purchase',
            'commission_held', 'commission_available', 'payout'
        )),
    actor_player_id INTEGER,
    order_id INTEGER,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0
);

INSERT INTO shop_promo_events__campaign (
    id, creator_id, promo_code_id, event_type, actor_player_id,
    order_id, meta_json, created_at
)
SELECT
    id, creator_id, promo_code_id, event_type, actor_player_id,
    order_id, meta_json, created_at
FROM shop_promo_events;

DROP TABLE shop_promo_events;
ALTER TABLE shop_promo_events__campaign RENAME TO shop_promo_events;

CREATE INDEX IF NOT EXISTS idx_shop_promo_events_creator_type
    ON shop_promo_events (creator_id, event_type, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_register_actor
    ON shop_promo_events (creator_id, actor_player_id)
    WHERE event_type = 'register' AND actor_player_id IS NOT NULL AND creator_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_purchase_order
    ON shop_promo_events (order_id)
    WHERE event_type = 'purchase' AND order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_held_order
    ON shop_promo_events (order_id)
    WHERE event_type = 'commission_held' AND order_id IS NOT NULL;
