-- Daily expedition value accumulator (UTC day bucket) + idempotent per-movement record.

CREATE TABLE IF NOT EXISTS expedition_daily_value (
    player_id INTEGER NOT NULL,
    day_bucket INTEGER NOT NULL,
    expo_value_total INTEGER NOT NULL DEFAULT 0,
    expedition_count INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, day_bucket)
);

CREATE INDEX IF NOT EXISTS idx_expedition_daily_value_bucket
    ON expedition_daily_value (day_bucket);

CREATE TABLE IF NOT EXISTS expedition_daily_recorded (
    movement_id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL,
    day_bucket INTEGER NOT NULL,
    expo_value INTEGER NOT NULL DEFAULT 0,
    recorded_at REAL NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_expedition_daily_recorded_player_day
    ON expedition_daily_recorded (player_id, day_bucket);
