-- Account options: email on users + audit log for self-service changes
-- Idempotent: migrate.py skips duplicate column / already exists errors.

ALTER TABLE users ADD COLUMN email TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
    ON users (LOWER(email))
    WHERE email IS NOT NULL AND email != '';

CREATE TABLE IF NOT EXISTS account_audit_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id    INTEGER NOT NULL,
    action       TEXT NOT NULL,
    payload_json TEXT,
    ip           TEXT,
    user_agent   TEXT,
    created_at   INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_account_audit_player
    ON account_audit_log (player_id, created_at DESC);
