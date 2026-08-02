-- 128_server_events.sql
-- Timed server-wide LiveOps events (production / expedition hold multipliers).

CREATE TABLE IF NOT EXISTS server_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    starts_at    INTEGER NOT NULL,
    ends_at      INTEGER NOT NULL,
    enabled      INTEGER NOT NULL DEFAULT 1,
    effects_json TEXT NOT NULL DEFAULT '[]',
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL,
    created_by   INTEGER
);

CREATE INDEX IF NOT EXISTS idx_server_events_window
    ON server_events(enabled, starts_at, ends_at);
