-- 142_command_initiation.sql
-- GC-Initiation: once-through do-first Command Initiation track (Phase 1).

CREATE TABLE IF NOT EXISTS player_initiation (
    player_id       INTEGER PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'active',
    step_index      INTEGER NOT NULL DEFAULT 0,
    progress_value  INTEGER NOT NULL DEFAULT 0,
    target_value    INTEGER NOT NULL DEFAULT 0,
    started_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    completed_at    INTEGER,
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_initiation_progress (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id        INTEGER NOT NULL,
    source_event_id  TEXT NOT NULL,
    delta            INTEGER NOT NULL DEFAULT 0,
    created_at       INTEGER NOT NULL,
    UNIQUE(player_id, source_event_id),
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_initiation_status
    ON player_initiation(status);

CREATE INDEX IF NOT EXISTS idx_player_initiation_progress_player
    ON player_initiation_progress(player_id);
