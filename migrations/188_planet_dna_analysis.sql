-- GC-TRAIT-R2C — durable per-colony DNA analysis cooldown.
-- No mutation or reroll of existing planet_dna, no automatic credits.
CREATE TABLE IF NOT EXISTS planet_dna_analysis (
    planet_id INTEGER PRIMARY KEY,
    last_scan_at REAL NOT NULL DEFAULT 0,
    scan_count INTEGER NOT NULL DEFAULT 0,
    last_xp_awarded INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
