-- 045_inventory_containers.sql
-- GC-540: player inventory items and container open audit log.

CREATE TABLE IF NOT EXISTS player_inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    planet_id INTEGER,
    item_key TEXT NOT NULL,
    item_type TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'common',
    amount INTEGER NOT NULL DEFAULT 0 CHECK(amount >= 0),
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_player_inventory_account_item
    ON player_inventory_items(user_id, item_key)
    WHERE planet_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_player_inventory_user
    ON player_inventory_items(user_id);

CREATE TABLE IF NOT EXISTS container_open_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    container_key TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_container_open_log_user
    ON container_open_log(user_id, created_at);
