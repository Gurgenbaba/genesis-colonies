-- 046_inventory_use_unlocks.sql
-- GC-541: permanent unlocks from blueprint items.

CREATE TABLE IF NOT EXISTS player_unlocks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    unlock_key TEXT NOT NULL,
    source_item_key TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(user_id, unlock_key)
);

CREATE INDEX IF NOT EXISTS idx_player_unlocks_user
    ON player_unlocks(user_id);
