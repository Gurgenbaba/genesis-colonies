-- GC-TIMEKEEPER-001 — Imperium time account (player-scoped balance + ledger)

CREATE TABLE IF NOT EXISTS timekeeper_balances (
    player_id INTEGER NOT NULL PRIMARY KEY REFERENCES players(id) ON DELETE CASCADE,
    balance_sec INTEGER NOT NULL DEFAULT 0 CHECK (balance_sec >= 0),
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS timekeeper_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    delta_sec INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    source TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_timekeeper_tx_player_created
    ON timekeeper_transactions (player_id, created_at DESC);
