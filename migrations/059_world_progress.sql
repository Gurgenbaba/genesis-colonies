-- GC-583D — Per-player familiarity progress for strategic expedition worlds

CREATE TABLE IF NOT EXISTS world_progress (
    player_id           INTEGER NOT NULL,
    world_key           TEXT NOT NULL,
    expedition_count    INTEGER NOT NULL DEFAULT 0 CHECK(expedition_count >= 0),
    last_expedition_at  REAL,
    PRIMARY KEY (player_id, world_key),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_world_progress_player_id ON world_progress(player_id);
