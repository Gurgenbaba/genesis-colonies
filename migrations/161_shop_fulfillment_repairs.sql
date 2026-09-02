-- P0 shop fulfillment recovery audit.
-- A fulfilled order may be repaired only once when an operator has verified that
-- rewards were never granted (for example after an unsafe manual status UPDATE).
CREATE TABLE IF NOT EXISTS shop_fulfillment_repairs (
    order_id INTEGER NOT NULL PRIMARY KEY REFERENCES shop_orders(id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    original_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    repaired_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shop_fulfillment_repairs_player
    ON shop_fulfillment_repairs(player_id, repaired_at);
