-- GC-RESEARCH-NET-ASC-001 — per-planet Research Lab Ascension state.
-- Capacity remains account-wide and resolves from the strongest lab; ranks never sum.

CREATE TABLE IF NOT EXISTS research_lab_ascension (
    planet_id INTEGER PRIMARY KEY,
    rank INTEGER NOT NULL DEFAULT 0 CHECK (rank >= 0 AND rank <= 5),
    ascended_at INTEGER,
    updated_at INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_lab_ascension_rank
    ON research_lab_ascension(rank);
