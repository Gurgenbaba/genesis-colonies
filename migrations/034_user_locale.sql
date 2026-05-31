-- Per-user UI / notification locale (de | en)
ALTER TABLE users ADD COLUMN locale TEXT NOT NULL DEFAULT 'de';
