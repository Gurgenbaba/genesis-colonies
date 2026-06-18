-- GC-650 — Genesis Timeline metadata on universe_news

ALTER TABLE universe_news ADD COLUMN version_tag TEXT NOT NULL DEFAULT '';
ALTER TABLE universe_news ADD COLUMN category TEXT NOT NULL DEFAULT '';
ALTER TABLE universe_news ADD COLUMN badge TEXT NOT NULL DEFAULT '';
ALTER TABLE universe_news ADD COLUMN image_url TEXT NOT NULL DEFAULT '';
ALTER TABLE universe_news ADD COLUMN is_major_release INTEGER NOT NULL DEFAULT 0;
ALTER TABLE universe_news ADD COLUMN is_draft INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_universe_news_version
    ON universe_news (version_tag, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_universe_news_draft
    ON universe_news (is_draft, published_at DESC);
