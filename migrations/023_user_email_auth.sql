-- Email verification + password reset tokens

ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN email_verification_token TEXT;
ALTER TABLE users ADD COLUMN password_reset_token TEXT;
ALTER TABLE users ADD COLUMN password_reset_expires_at INTEGER;

CREATE INDEX IF NOT EXISTS idx_users_email_verify_token
    ON users (email_verification_token)
    WHERE email_verification_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_password_reset_token
    ON users (password_reset_token)
    WHERE password_reset_token IS NOT NULL;
