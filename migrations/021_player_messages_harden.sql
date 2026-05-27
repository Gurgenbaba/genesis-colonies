-- 021_player_messages_harden.sql
-- Normalize legacy player_messages rows (pre-patch NULL / zero flags).

UPDATE player_messages SET is_read = 0 WHERE is_read IS NULL;
UPDATE player_messages SET is_archived = 0 WHERE is_archived IS NULL;
UPDATE player_messages SET deleted_at = NULL WHERE deleted_at = 0;
