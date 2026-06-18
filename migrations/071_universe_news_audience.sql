-- GC-653 — player vs dev audience for /news vs /devlog

ALTER TABLE universe_news ADD COLUMN audience TEXT NOT NULL DEFAULT 'player';
ALTER TABLE universe_news ADD COLUMN entry_section TEXT NOT NULL DEFAULT '';

UPDATE universe_news SET audience = 'dev' WHERE source_ref LIKE 'git:%';
UPDATE universe_news SET audience = 'dev' WHERE lower(version_tag) IN ('development', 'dev', 'ongoing');
UPDATE universe_news SET audience = 'dev' WHERE category = 'DEVBLOG';

CREATE INDEX IF NOT EXISTS idx_universe_news_audience
    ON universe_news (audience, published_at DESC);
