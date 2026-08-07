-- 146_space_lottery.sql
-- EPIC-28 / GC-2801: Space Lottery (Timekeeper wager + weekly tombola + instant games)

CREATE TABLE IF NOT EXISTS space_lottery_weeks (
    week_id TEXT PRIMARY KEY,
    pool_sec INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    ticket_price_sec INTEGER NOT NULL DEFAULT 300,
    server_seed_hash TEXT,
    server_seed TEXT,
    winner_player_id INTEGER,
    winner_tickets INTEGER,
    drawn_at REAL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY(winner_player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_space_lottery_weeks_status
    ON space_lottery_weeks(status, week_id DESC);

CREATE TABLE IF NOT EXISTS space_lottery_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id TEXT NOT NULL,
    player_id INTEGER NOT NULL,
    ticket_count INTEGER NOT NULL DEFAULT 0,
    spent_sec INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL,
    FOREIGN KEY(week_id) REFERENCES space_lottery_weeks(week_id),
    FOREIGN KEY(player_id) REFERENCES players(id),
    UNIQUE(week_id, player_id)
);

CREATE INDEX IF NOT EXISTS idx_space_lottery_tickets_player
    ON space_lottery_tickets(player_id, week_id DESC);

CREATE TABLE IF NOT EXISTS space_lottery_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    game TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    bet_sec INTEGER NOT NULL,
    payout_sec INTEGER NOT NULL DEFAULT 0,
    seed_hash TEXT NOT NULL,
    seed TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    request_id TEXT,
    created_at REAL NOT NULL,
    settled_at REAL,
    FOREIGN KEY(player_id) REFERENCES players(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_space_lottery_rounds_request
    ON space_lottery_rounds(player_id, request_id)
    WHERE request_id IS NOT NULL AND request_id != '';

CREATE INDEX IF NOT EXISTS idx_space_lottery_rounds_player_status
    ON space_lottery_rounds(player_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS space_lottery_wagers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    delta_sec INTEGER NOT NULL,
    balance_after INTEGER,
    ref_type TEXT,
    ref_id TEXT,
    request_id TEXT,
    created_at REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_space_lottery_wagers_player
    ON space_lottery_wagers(player_id, created_at DESC);

CREATE TABLE IF NOT EXISTS space_lottery_daily (
    player_id INTEGER NOT NULL,
    day_bucket INTEGER NOT NULL,
    wagered_sec INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, day_bucket),
    FOREIGN KEY(player_id) REFERENCES players(id)
);
