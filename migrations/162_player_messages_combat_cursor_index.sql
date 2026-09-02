-- GC-PERF-HOF-001
-- GC-REQUIRES-TABLES: player_messages
-- Incremental Combat HoF sync reads one ordered combat-message stream via
-- category='combat' AND id > last_message_id. Keep that cursor index-backed.

CREATE INDEX IF NOT EXISTS idx_player_messages_combat_cursor
    ON player_messages (category, id);
