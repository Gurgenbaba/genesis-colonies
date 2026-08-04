-- GC-BST-10: per-planet building stage layout overrides (display-only)

CREATE TABLE IF NOT EXISTS planet_building_stage_layout (
    planet_id INTEGER NOT NULL,
    building_key TEXT NOT NULL,
    left_pct REAL NOT NULL,
    top_pct REAL NOT NULL,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, building_key)
);

CREATE INDEX IF NOT EXISTS idx_planet_building_stage_layout_planet
    ON planet_building_stage_layout (planet_id);
