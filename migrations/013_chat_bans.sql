-- 013_chat_bans.sql
-- Genesis TChat: persistent chat bans (separate from global account bans).

CREATE TABLE IF NOT EXISTS chat_bans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL UNIQUE,
    banned_by   INTEGER NOT NULL,
    reason      TEXT,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(banned_by) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_bans_active ON chat_bans(player_id, is_active);
