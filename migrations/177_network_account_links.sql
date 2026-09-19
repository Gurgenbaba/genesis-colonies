-- GC-NETWORK-AUTH-001 — one Genesis identity, isolated universe game states.

CREATE TABLE IF NOT EXISTS network_account_links (
    local_user_id      INTEGER PRIMARY KEY,
    network_account_id TEXT NOT NULL UNIQUE,
    authority_key      TEXT NOT NULL DEFAULT 'dev',
    created_at         INTEGER NOT NULL,
    last_login_at      INTEGER NOT NULL,
    FOREIGN KEY (local_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_network_account_links_account
    ON network_account_links(network_account_id);

CREATE TABLE IF NOT EXISTS network_auth_nonces (
    nonce       TEXT PRIMARY KEY,
    expires_at  INTEGER NOT NULL,
    consumed_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_network_auth_nonces_expiry
    ON network_auth_nonces(expires_at);
