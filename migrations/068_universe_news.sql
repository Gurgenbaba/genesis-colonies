-- GC-642 — Universe news / changelog (MOTD history)

CREATE TABLE IF NOT EXISTS universe_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    published_at INTEGER NOT NULL,
    is_banner INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_universe_news_published
    ON universe_news (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_universe_news_banner
    ON universe_news (is_banner, published_at DESC);
