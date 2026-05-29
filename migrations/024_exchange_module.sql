-- 024_exchange_module.sql
-- Instant Ferronit <-> Crytite exchange (click trade, no fleets).

CREATE TABLE IF NOT EXISTS exchange_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    give_resource TEXT NOT NULL CHECK(give_resource IN ('metal', 'crystal')),
    give_amount REAL NOT NULL CHECK(give_amount > 0),
    receive_resource TEXT NOT NULL CHECK(receive_resource IN ('metal', 'crystal')),
    receive_amount REAL NOT NULL CHECK(receive_amount > 0),
    created_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exchange_log_player_time
    ON exchange_log(player_id, created_at DESC);

ALTER TABLE players ADD COLUMN exchange_daily_used REAL NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN exchange_daily_reset_at REAL NOT NULL DEFAULT 0;

INSERT OR IGNORE INTO game_settings (key, value) VALUES
('exchange_enabled', '1'),
('exchange_rate_metal_to_crystal', '0.8'),
('exchange_rate_crystal_to_metal', '0.8'),
('exchange_daily_limit', '500000000'),
('exchange_min_amount', '100');
