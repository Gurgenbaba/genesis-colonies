-- 047_auction_house.sql
-- GC-550: Lootbox auction house (event boxes excluded from rotation).

CREATE TABLE IF NOT EXISTS lootbox_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    box_key TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    created_at INTEGER NOT NULL,
    opened_at INTEGER,
    FOREIGN KEY(player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_lootbox_inventory_player
    ON lootbox_inventory(player_id, created_at);

CREATE TABLE IF NOT EXISTS auction_house_listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    box_key TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_price INTEGER NOT NULL,
    current_bid INTEGER NOT NULL DEFAULT 0,
    current_bidder_id INTEGER,
    current_bid_planet_id INTEGER,
    starts_at INTEGER NOT NULL,
    ends_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(current_bidder_id) REFERENCES players(id),
    FOREIGN KEY(current_bid_planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_auction_listings_active
    ON auction_house_listings(status, ends_at);

CREATE TABLE IF NOT EXISTS auction_house_bids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    planet_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    refunded INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(listing_id) REFERENCES auction_house_listings(id),
    FOREIGN KEY(player_id) REFERENCES players(id),
    FOREIGN KEY(planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_auction_bids_listing
    ON auction_house_bids(listing_id, created_at);
