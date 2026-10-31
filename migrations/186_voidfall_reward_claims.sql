-- VOIDFALL Release 2: bounded, per-account, per-UTC-day event claims.
-- Separate from Battle Pass / Login Rewards / inventory so no double-credit paths.
-- No automatic rewards or economy modifications during migration.
CREATE TABLE IF NOT EXISTS voidfall_reward_claims (
    user_id INTEGER NOT NULL,
    claim_key TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '[]',
    claimed_at REAL NOT NULL,
    PRIMARY KEY (user_id, claim_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
