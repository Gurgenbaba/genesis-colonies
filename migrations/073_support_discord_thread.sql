-- GC-656B: Discord forum thread link for support tickets
ALTER TABLE support_tickets ADD COLUMN discord_thread_id TEXT;

CREATE INDEX IF NOT EXISTS idx_support_tickets_discord_thread
    ON support_tickets(discord_thread_id)
    WHERE discord_thread_id IS NOT NULL;
