-- 105_asteroid_engagements.sql
-- Durable per-player asteroid hunt engagement (survives fleet resources_json wipe).

CREATE TABLE IF NOT EXISTS asteroid_engagements (
    player_id   INTEGER NOT NULL,
    asteroid_id INTEGER NOT NULL,
    engaged_at  REAL NOT NULL,
    PRIMARY KEY (player_id, asteroid_id),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY (asteroid_id) REFERENCES asteroid_fields(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asteroid_engagements_asteroid
    ON asteroid_engagements(asteroid_id);

CREATE INDEX IF NOT EXISTS idx_asteroid_engagements_player
    ON asteroid_engagements(player_id);
