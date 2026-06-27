-- 082_collector_exchange.sql
-- GC-965A: Collector Exchange foundations (lifetime stats, audit log, idempotent redemptions).

CREATE TABLE IF NOT EXISTS collector_lifetime_stats (
    user_id INTEGER NOT NULL,
    item_key TEXT NOT NULL,
    lifetime_acquired INTEGER NOT NULL DEFAULT 0 CHECK(lifetime_acquired >= 0),
    lifetime_redeemed INTEGER NOT NULL DEFAULT 0 CHECK(lifetime_redeemed >= 0),
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, item_key),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collector_lifetime_stats_user
    ON collector_lifetime_stats(user_id);

CREATE TABLE IF NOT EXISTS collector_exchange_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    offer_key TEXT NOT NULL,
    input_key TEXT NOT NULL,
    input_amount INTEGER NOT NULL CHECK(input_amount > 0),
    rewards_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_collector_exchange_log_user
    ON collector_exchange_log(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS collector_exchange_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    offer_key TEXT NOT NULL,
    request_id TEXT NOT NULL,
    input_key TEXT NOT NULL,
    input_amount INTEGER NOT NULL CHECK(input_amount > 0),
    rewards_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_collector_exchange_redemptions_request
    ON collector_exchange_redemptions(user_id, request_id);

CREATE INDEX IF NOT EXISTS idx_collector_exchange_redemptions_user
    ON collector_exchange_redemptions(user_id, created_at DESC);
