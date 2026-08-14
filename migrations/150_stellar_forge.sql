-- 150_stellar_forge.sql
-- EPIC-30 / GC-3001: Stellar Forge Phase 1 — orbital shipyard Ascension campaign state

CREATE TABLE IF NOT EXISTS planet_shipyard_ascension (
    planet_id INTEGER NOT NULL,
    forge_rank INTEGER NOT NULL DEFAULT 0,
    campaign_active INTEGER NOT NULL DEFAULT 0,
    campaign_started_at REAL,
    tribute_paid INTEGER NOT NULL DEFAULT 0,
    hull_mass_progress INTEGER NOT NULL DEFAULT 0,
    hull_mass_by_role TEXT NOT NULL DEFAULT '{}',
    operational_protocols_done TEXT NOT NULL DEFAULT '[]',
    forge_cores_committed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_planet_shipyard_ascension_rank
    ON planet_shipyard_ascension(forge_rank);

CREATE TABLE IF NOT EXISTS player_forge_cores (
    player_id INTEGER NOT NULL PRIMARY KEY,
    forge_cores INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players(id)
);
