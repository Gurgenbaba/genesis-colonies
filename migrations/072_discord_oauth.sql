-- GC-733A: Discord OAuth login/register
ALTER TABLE users ADD COLUMN discord_id TEXT;
ALTER TABLE users ADD COLUMN discord_username TEXT;
ALTER TABLE users ADD COLUMN discord_avatar TEXT;
ALTER TABLE users ADD COLUMN discord_email TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_discord_id
ON users(discord_id)
WHERE discord_id IS NOT NULL;
