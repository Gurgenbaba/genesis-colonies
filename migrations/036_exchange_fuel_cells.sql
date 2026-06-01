-- 036_exchange_fuel_cells.sql
-- Extend exchange_log for unified 3-resource trader (GC-402).

CREATE TABLE IF NOT EXISTS exchange_log_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    give_resource TEXT NOT NULL CHECK(give_resource IN ('metal', 'crystal', 'fuel_cells')),
    give_amount REAL NOT NULL CHECK(give_amount > 0),
    receive_resource TEXT NOT NULL CHECK(receive_resource IN ('metal', 'crystal', 'fuel_cells')),
    receive_amount REAL NOT NULL CHECK(receive_amount > 0),
    created_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

INSERT INTO exchange_log_new (
    id, player_id, planet_id, give_resource, give_amount,
    receive_resource, receive_amount, created_at
)
SELECT
    id, player_id, planet_id, give_resource, give_amount,
    receive_resource, receive_amount, created_at
FROM exchange_log;

DROP TABLE exchange_log;

ALTER TABLE exchange_log_new RENAME TO exchange_log;

CREATE INDEX IF NOT EXISTS idx_exchange_log_player_time
    ON exchange_log(player_id, created_at DESC);
