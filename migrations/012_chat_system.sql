-- 012_chat_system.sql
-- Genesis TChat: rooms, messages, mutes, UI state + minimal alliances for alliance chat.

-- ---------------------------------------------------------------------------
-- Alliances (minimal – required for alliance-scoped chat)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alliances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tag         TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS alliance_members (
    alliance_id INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member',
    joined_at   INTEGER NOT NULL,
    PRIMARY KEY (alliance_id, player_id),
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alliance_members_player ON alliance_members(player_id);
CREATE INDEX IF NOT EXISTS idx_alliance_members_alliance ON alliance_members(alliance_id);

-- ---------------------------------------------------------------------------
-- Chat rooms
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_rooms (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    room_key     TEXT NOT NULL UNIQUE,
    room_type    TEXT NOT NULL,
    title        TEXT NOT NULL,
    alliance_id  INTEGER,
    created_by   INTEGER,
    is_private   INTEGER NOT NULL DEFAULT 0,
    is_system    INTEGER NOT NULL DEFAULT 0,
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_rooms_room_key ON chat_rooms(room_key);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_alliance_id ON chat_rooms(alliance_id);
CREATE INDEX IF NOT EXISTS idx_chat_rooms_type ON chat_rooms(room_type);

-- ---------------------------------------------------------------------------
-- Room membership (DM + optional explicit membership)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_room_members (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id               INTEGER NOT NULL,
    player_id             INTEGER NOT NULL,
    role                  TEXT NOT NULL DEFAULT 'member',
    last_read_message_id  INTEGER,
    muted_until           INTEGER,
    joined_at             INTEGER NOT NULL,
    UNIQUE(room_id, player_id),
    FOREIGN KEY(room_id) REFERENCES chat_rooms(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_room_members_player_room ON chat_room_members(player_id, room_id);
CREATE INDEX IF NOT EXISTS idx_chat_room_members_room ON chat_room_members(room_id);

-- ---------------------------------------------------------------------------
-- Messages
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id         INTEGER NOT NULL,
    sender_id       INTEGER,
    target_user_id  INTEGER,
    alliance_id     INTEGER,
    message_type    TEXT NOT NULL DEFAULT 'normal',
    body            TEXT NOT NULL,
    body_rendered   TEXT,
    created_at      INTEGER NOT NULL,
    edited_at       INTEGER,
    deleted_at      INTEGER,
    deleted_by      INTEGER,
    FOREIGN KEY(room_id) REFERENCES chat_rooms(id) ON DELETE CASCADE,
    FOREIGN KEY(sender_id) REFERENCES players(id) ON DELETE SET NULL,
    FOREIGN KEY(target_user_id) REFERENCES players(id) ON DELETE SET NULL,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE SET NULL,
    FOREIGN KEY(deleted_by) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_room_id ON chat_messages(room_id, id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);

-- ---------------------------------------------------------------------------
-- Mutes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_mutes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   INTEGER NOT NULL,
    muted_by    INTEGER NOT NULL,
    scope       TEXT NOT NULL,
    room_id     INTEGER,
    reason      TEXT,
    muted_until INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(muted_by) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(room_id) REFERENCES chat_rooms(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_mutes_player ON chat_mutes(player_id, muted_until);

-- ---------------------------------------------------------------------------
-- Per-player UI state
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_user_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL UNIQUE,
    is_open         INTEGER NOT NULL DEFAULT 0,
    is_minimized    INTEGER NOT NULL DEFAULT 1,
    active_room_id  INTEGER,
    width           INTEGER NOT NULL DEFAULT 380,
    height          INTEGER NOT NULL DEFAULT 480,
    pos_x           INTEGER NOT NULL DEFAULT 0,
    pos_y           INTEGER NOT NULL DEFAULT 0,
    updated_at      INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(active_room_id) REFERENCES chat_rooms(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- Last whisper partner (for /r)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_whisper_state (
    player_id           INTEGER PRIMARY KEY,
    last_partner_id     INTEGER NOT NULL,
    last_dm_room_id     INTEGER,
    updated_at          INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(last_partner_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(last_dm_room_id) REFERENCES chat_rooms(id) ON DELETE SET NULL
);

-- ---------------------------------------------------------------------------
-- Default rooms (idempotent)
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO chat_rooms (room_key, room_type, title, alliance_id, created_by, is_private, is_system, is_active, created_at, updated_at)
VALUES
    ('global', 'global', 'Global', NULL, NULL, 0, 0, 1, strftime('%s','now'), strftime('%s','now')),
    ('system', 'system', 'System', NULL, NULL, 0, 1, 1, strftime('%s','now'), strftime('%s','now')),
    ('admin', 'admin', 'Admin', NULL, NULL, 1, 0, 1, strftime('%s','now'), strftime('%s','now'));
