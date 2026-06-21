-- GC-807: Account safety — vacation mode, deferred deletion, controlled reset.

ALTER TABLE players ADD COLUMN vacation_mode_active INTEGER NOT NULL DEFAULT 0;
ALTER TABLE players ADD COLUMN vacation_locked_until INTEGER;
ALTER TABLE players ADD COLUMN account_deletion_requested_at INTEGER;
ALTER TABLE players ADD COLUMN account_deletion_due_at INTEGER;
ALTER TABLE players ADD COLUMN account_deleted_at INTEGER;

CREATE INDEX IF NOT EXISTS idx_players_account_deletion_due
    ON players (account_deletion_due_at)
    WHERE account_deletion_due_at IS NOT NULL AND account_deleted_at IS NULL;
