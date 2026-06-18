-- 064_referrals.sql
-- GC-703: Referral codes, qualified referrals, tier reward claims.

ALTER TABLE users ADD COLUMN registered_at INTEGER;
ALTER TABLE users ADD COLUMN registration_ip TEXT;

CREATE TABLE IF NOT EXISTS player_referral_codes (
    player_id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_player_referral_codes_code
    ON player_referral_codes(code);

CREATE TABLE IF NOT EXISTS player_referrals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    referred_player_id INTEGER NOT NULL UNIQUE,
    referrer_player_id INTEGER NOT NULL,
    referral_code TEXT NOT NULL,
    apply_ip TEXT,
    same_ip_flag INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    qualified_at INTEGER,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(referred_player_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(referrer_player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_referrals_referrer_status
    ON player_referrals(referrer_player_id, status, same_ip_flag);

CREATE TABLE IF NOT EXISTS referral_reward_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    reward_scope TEXT NOT NULL,
    reward_key TEXT NOT NULL,
    box_key TEXT,
    amount INTEGER NOT NULL DEFAULT 1,
    claimed_at INTEGER NOT NULL,
    UNIQUE(player_id, reward_scope, reward_key),
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_referral_reward_claims_player
    ON referral_reward_claims(player_id, reward_scope);
