-- EPIC-23 Payment / Shop — products, orders, webhook event audit

CREATE TABLE IF NOT EXISTS shop_products (
    sku TEXT NOT NULL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('entitlement', 'timekeeper', 'inventory_bundle')),
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

CREATE TABLE IF NOT EXISTS shop_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('stripe', 'paypal', 'test')),
    provider_session_id TEXT,
    provider_payment_id TEXT,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    currency TEXT NOT NULL DEFAULT 'eur',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'paid', 'fulfilled', 'failed', 'refunded')),
    fulfill_reason TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    paid_at REAL,
    fulfilled_at REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_shop_orders_provider_payment
    ON shop_orders (provider, provider_payment_id)
    WHERE provider_payment_id IS NOT NULL AND provider_payment_id != '';

CREATE INDEX IF NOT EXISTS idx_shop_orders_player
    ON shop_orders (player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_shop_orders_session
    ON shop_orders (provider, provider_session_id);

CREATE TABLE IF NOT EXISTS shop_payment_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    event_id TEXT NOT NULL,
    order_id INTEGER REFERENCES shop_orders(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    processed_at REAL NOT NULL DEFAULT 0,
    UNIQUE (provider, event_id)
);

CREATE INDEX IF NOT EXISTS idx_shop_payment_events_order
    ON shop_payment_events (order_id);
