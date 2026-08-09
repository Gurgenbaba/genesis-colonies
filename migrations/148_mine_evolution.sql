-- 148_mine_evolution.sql
-- EPIC-29 / GC-2901: Mine Evolution Phase 1 — planet-scoped rank per production mine

CREATE TABLE IF NOT EXISTS planet_mine_evolution (
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    evolution_rank INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, building_type),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_planet_mine_evolution_planet
    ON planet_mine_evolution(planet_id);
