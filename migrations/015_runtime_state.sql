-- 015_runtime_state.sql
-- Key-value store for cron tick / worker runtime metrics (admin health).

CREATE TABLE IF NOT EXISTS runtime_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_state_updated
    ON runtime_state (updated_at DESC);
