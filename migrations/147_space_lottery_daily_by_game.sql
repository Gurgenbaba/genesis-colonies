-- GC-2809: per-game daily wager volume (tombola / mines / crash)
CREATE TABLE IF NOT EXISTS space_lottery_daily_game (
    player_id INTEGER NOT NULL,
    day_bucket INTEGER NOT NULL,
    game TEXT NOT NULL,
    wagered_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, day_bucket, game),
    FOREIGN KEY(player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_space_lottery_daily_game_bucket
    ON space_lottery_daily_game(day_bucket, game);
