-- 048_vote_rewards.sql
-- GC-551: TopG vote postback rewards (pending → claim in Vote Center).

CREATE TABLE IF NOT EXISTS vote_rewards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    vote_ip TEXT,
    provider_ref TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reward_key TEXT,
    reward_payload_json TEXT,
    voted_at INTEGER NOT NULL,
    claimed_at INTEGER,
    created_at INTEGER NOT NULL,
    UNIQUE(provider, user_id, provider_ref),
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_vote_rewards_user_status
    ON vote_rewards(user_id, status);

CREATE INDEX IF NOT EXISTS idx_vote_rewards_provider_user_time
    ON vote_rewards(provider, user_id, voted_at);
