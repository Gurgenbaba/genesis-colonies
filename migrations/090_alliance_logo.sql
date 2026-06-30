-- 090_alliance_logo.sql
-- Alliance emblem upload (same pipeline as player avatars — GC-AL-009)

ALTER TABLE alliances ADD COLUMN logo_url TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS alliance_logos (
    alliance_id INTEGER PRIMARY KEY,
    image_blob  BLOB NOT NULL,
    mime_type   TEXT NOT NULL DEFAULT 'image/webp',
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE
);
