-- 065_support_discord_thread.sql
-- Link ingame support tickets to Discord forum threads (GC-656C).

ALTER TABLE support_tickets ADD COLUMN discord_thread_id TEXT;

CREATE INDEX IF NOT EXISTS idx_support_tickets_discord_thread
    ON support_tickets(discord_thread_id);
