-- GC-808: Persistent player avatars (DB blob storage, survives deploy).

CREATE TABLE IF NOT EXISTS player_avatars (
    player_id   INTEGER PRIMARY KEY,
    image_blob  BLOB NOT NULL,
    mime_type   TEXT NOT NULL,
    updated_at  INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);
