-- GC-P0-CHRONICLES-PERSISTENCE: durable player chronicle archive (independent of inbox).

CREATE TABLE IF NOT EXISTS chronicle_entries (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_type          TEXT NOT NULL,
    player_id           INTEGER NOT NULL,
    planet_id           INTEGER,
    related_player_id   INTEGER,
    source_message_id   INTEGER,
    source_event_id     TEXT,
    title_key           TEXT,
    body_json           TEXT NOT NULL DEFAULT '{}',
    score_value         INTEGER NOT NULL DEFAULT 0,
    occurred_at         INTEGER NOT NULL,
    created_at          INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chronicle_entries_type_score
    ON chronicle_entries (entry_type, score_value DESC, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_chronicle_entries_player
    ON chronicle_entries (player_id, occurred_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chronicle_entries_player_event
    ON chronicle_entries (player_id, entry_type, source_event_id)
    WHERE source_event_id IS NOT NULL;
