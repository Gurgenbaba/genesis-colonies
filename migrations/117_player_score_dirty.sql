-- 117_player_score_dirty.sql
-- GC-SCORE-PERF-001: deferred score refresh — persistent dirty marker with versioning.

CREATE TABLE IF NOT EXISTS player_score_dirty (
    player_id     INTEGER PRIMARY KEY,
    dirty_version INTEGER NOT NULL DEFAULT 1,
    dirty_since   REAL NOT NULL,
    updated_at    REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_score_dirty_since
    ON player_score_dirty (dirty_since ASC, player_id ASC);
