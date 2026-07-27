-- 116_genesis_story_ops.sql
-- GC-2501: Genesis Story Ops schema (persistent lore arcs / side ops).

CREATE TABLE IF NOT EXISTS player_story_flags (
    player_id   INTEGER NOT NULL,
    flag_key    TEXT NOT NULL,
    flag_value  TEXT NOT NULL DEFAULT '1',
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (player_id, flag_key),
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_story_flags_player
    ON player_story_flags(player_id);

CREATE TABLE IF NOT EXISTS player_story_arcs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id       INTEGER NOT NULL,
    pack_id         TEXT NOT NULL,
    arc_id          TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    chapter_index   INTEGER NOT NULL DEFAULT 0,
    beat_index      INTEGER NOT NULL DEFAULT 0,
    progress_value  INTEGER NOT NULL DEFAULT 0,
    target_value    INTEGER NOT NULL DEFAULT 0,
    started_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    UNIQUE(player_id, pack_id, arc_id),
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_story_arcs_player_status
    ON player_story_arcs(player_id, status);

CREATE TABLE IF NOT EXISTS player_story_progress (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_arc_id    INTEGER NOT NULL,
    source_event_id  TEXT NOT NULL,
    delta            INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL,
    UNIQUE(player_arc_id, source_event_id),
    FOREIGN KEY(player_arc_id) REFERENCES player_story_arcs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_story_progress_arc
    ON player_story_progress(player_arc_id);
