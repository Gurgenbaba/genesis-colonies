-- GC-POL-05 — Player resolution vote sessions (JA/NEIN) beside active resolution overlay

CREATE TABLE IF NOT EXISTS gd_resolution_sessions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    galaxy           INTEGER NOT NULL,
    resolution_key   TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'vote_open',
    vote_start_at    INTEGER NOT NULL,
    vote_end_at      INTEGER NOT NULL,
    yes_votes        INTEGER NOT NULL DEFAULT 0,
    no_votes         INTEGER NOT NULL DEFAULT 0,
    quorum_needed    INTEGER NOT NULL DEFAULT 0,
    total_eligible   INTEGER NOT NULL DEFAULT 0,
    result           TEXT,
    created_by       INTEGER,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL,
    FOREIGN KEY (resolution_key) REFERENCES gd_resolution_definitions(resolution_key)
);

CREATE INDEX IF NOT EXISTS idx_gd_resolution_sessions_galaxy_status
    ON gd_resolution_sessions(galaxy, status);

CREATE TABLE IF NOT EXISTS gd_resolution_session_votes (
    session_id   INTEGER NOT NULL,
    player_id    INTEGER NOT NULL,
    choice       TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    PRIMARY KEY (session_id, player_id),
    FOREIGN KEY (session_id) REFERENCES gd_resolution_sessions(id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_gd_resolution_session_votes_player
    ON gd_resolution_session_votes(player_id);
