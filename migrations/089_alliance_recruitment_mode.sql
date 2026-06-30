-- 089_alliance_recruitment_mode.sql
-- GC-AL-008: Alliance recruitment mode (open | application_only | closed)

ALTER TABLE alliances ADD COLUMN recruitment_mode TEXT NOT NULL DEFAULT 'open';
