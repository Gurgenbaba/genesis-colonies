-- Creator Promo Codes — vanity code, commission ledger, funnel events (AAA partner program)

CREATE TABLE IF NOT EXISTS shop_creators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    player_id INTEGER NOT NULL UNIQUE REFERENCES players(id) ON DELETE CASCADE,
    paypal_email TEXT,
    payout_note TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    terms_acked_at REAL,
    terms_version TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shop_creators_active
    ON shop_creators (active, id);

CREATE TABLE IF NOT EXISTS shop_promo_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    creator_id INTEGER NOT NULL REFERENCES shop_creators(id) ON DELETE CASCADE,
    discount_bps INTEGER NOT NULL DEFAULT 1000 CHECK (discount_bps >= 0 AND discount_bps <= 9000),
    commission_bps INTEGER NOT NULL DEFAULT 1000 CHECK (commission_bps >= 0 AND commission_bps <= 5000),
    max_redemptions INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shop_promo_codes_creator
    ON shop_promo_codes (creator_id, active);

CREATE TABLE IF NOT EXISTS shop_creator_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL REFERENCES shop_creators(id) ON DELETE CASCADE,
    order_id INTEGER NOT NULL UNIQUE REFERENCES shop_orders(id) ON DELETE CASCADE,
    buyer_player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    promo_code_id INTEGER REFERENCES shop_promo_codes(id) ON DELETE SET NULL,
    gross_cents INTEGER NOT NULL CHECK (gross_cents >= 0),
    commission_cents INTEGER NOT NULL CHECK (commission_cents >= 0),
    status TEXT NOT NULL DEFAULT 'held'
        CHECK (status IN ('held', 'available', 'paid', 'reversed')),
    available_at REAL,
    payout_batch_id INTEGER,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shop_creator_ledger_creator_status
    ON shop_creator_ledger (creator_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS shop_creator_payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL REFERENCES shop_creators(id) ON DELETE CASCADE,
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
    note TEXT NOT NULL DEFAULT '',
    marked_by INTEGER,
    created_at REAL NOT NULL DEFAULT 0,
    csv_snapshot_json TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_shop_creator_payouts_creator
    ON shop_creator_payouts (creator_id, created_at DESC);

CREATE TABLE IF NOT EXISTS shop_promo_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL REFERENCES shop_creators(id) ON DELETE CASCADE,
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

CREATE INDEX IF NOT EXISTS idx_shop_promo_events_creator_type
    ON shop_promo_events (creator_id, event_type, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_register_actor
    ON shop_promo_events (creator_id, actor_player_id)
    WHERE event_type = 'register' AND actor_player_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_purchase_order
    ON shop_promo_events (order_id)
    WHERE event_type = 'purchase' AND order_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_promo_events_held_order
    ON shop_promo_events (order_id)
    WHERE event_type = 'commission_held' AND order_id IS NOT NULL;

ALTER TABLE shop_orders ADD COLUMN promo_code_id INTEGER REFERENCES shop_promo_codes(id) ON DELETE SET NULL;
ALTER TABLE shop_orders ADD COLUMN list_amount_cents INTEGER;
ALTER TABLE shop_orders ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE shop_orders ADD COLUMN commission_cents INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_shop_orders_promo
    ON shop_orders (promo_code_id)
    WHERE promo_code_id IS NOT NULL;
