-- GC-652 — idempotent git import source reference

ALTER TABLE universe_news ADD COLUMN source_ref TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_universe_news_source_ref
    ON universe_news (source_ref)
    WHERE source_ref != '';
