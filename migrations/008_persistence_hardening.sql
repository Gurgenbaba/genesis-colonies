-- 008_persistence_hardening.sql
-- Production persistence: idempotency, queue indexes, research_queue.start_at
-- Portable SQL (SQLite + Postgres compatible where noted)

-- ---------------------------------------------------------------------------
-- Idempotency store (API request replay / double-submit guard)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_idempotency (
    user_id        INTEGER NOT NULL,
    request_id     TEXT NOT NULL,
    response_json  TEXT NOT NULL,
    created_at     REAL NOT NULL,
    PRIMARY KEY (user_id, request_id)
);

-- ---------------------------------------------------------------------------
-- research_queue.start_at (nullable – legacy rows remain valid)
-- ---------------------------------------------------------------------------
ALTER TABLE research_queue ADD COLUMN start_at REAL;

-- ---------------------------------------------------------------------------
-- Queue / idempotency performance indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_build_queue_planet_id
    ON build_queue (planet_id);

CREATE INDEX IF NOT EXISTS idx_build_queue_planet_finish
    ON build_queue (planet_id, finish_time);

CREATE INDEX IF NOT EXISTS idx_research_queue_user_id
    ON research_queue (user_id);

CREATE INDEX IF NOT EXISTS idx_research_queue_user_finish
    ON research_queue (user_id, finish_at);

CREATE INDEX IF NOT EXISTS idx_action_idempotency_created
    ON action_idempotency (created_at);

CREATE INDEX IF NOT EXISTS idx_action_idempotency_user_created
    ON action_idempotency (user_id, created_at);
