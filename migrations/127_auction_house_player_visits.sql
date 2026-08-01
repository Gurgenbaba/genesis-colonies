-- 127_auction_house_player_visits.sql
-- Track last Auktionshaus visit for nav-badge "new listing" attention.

CREATE TABLE IF NOT EXISTS auction_house_player_visits (
    player_id INTEGER PRIMARY KEY NOT NULL,
    last_visited_at INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);
