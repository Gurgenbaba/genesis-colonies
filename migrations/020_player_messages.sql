-- 020_player_messages.sql
-- Internal player messaging (OGame-style inbox).

CREATE TABLE IF NOT EXISTS player_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_player_id INTEGER NOT NULL,
    sender_player_id INTEGER,
    sender_name TEXT,
    category TEXT NOT NULL DEFAULT 'system',
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    is_archived INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT,
    created_at INTEGER NOT NULL,
    read_at INTEGER,
    deleted_at INTEGER,
    FOREIGN KEY(recipient_player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(sender_player_id) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_player_messages_recipient_list
    ON player_messages(recipient_player_id, deleted_at, is_archived, created_at DESC);

-- Composite index for unread counts (no partial index — max SQLite/Railway compat).
CREATE INDEX IF NOT EXISTS idx_player_messages_recipient_unread
    ON player_messages(recipient_player_id, is_archived, is_read, deleted_at);
