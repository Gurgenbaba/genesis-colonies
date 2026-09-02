-- GC-PERF-HOF-001
-- SQLite-only numbered migration. PostgreSQL creates the same index through
-- game/pg_hotpath_indexes.py with CREATE INDEX CONCURRENTLY so the old live
-- deployment can keep writing player_messages during a rolling deploy.
-- sqlite_sequence is the backend sentinel: present for SQLite AUTOINCREMENT
-- schemas, absent from the PostgreSQL application schema.
-- GC-REQUIRES-TABLES: player_messages, sqlite_sequence

CREATE INDEX IF NOT EXISTS idx_player_messages_combat_cursor
    ON player_messages (category, id);
