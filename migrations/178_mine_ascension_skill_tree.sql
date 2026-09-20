-- 178_mine_ascension_skill_tree.sql
-- Prestige skill-tree mine Ascension: permanent run state + per-mine skill tree.

CREATE TABLE IF NOT EXISTS planet_mine_ascension_state (
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    ascension_count INTEGER NOT NULL DEFAULT 0,
    points_earned INTEGER NOT NULL DEFAULT 0,
    points_unspent INTEGER NOT NULL DEFAULT 0,
    best_depth INTEGER NOT NULL DEFAULT 0,
    last_depth INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, building_type),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_planet_mine_ascension_state_planet
    ON planet_mine_ascension_state(planet_id);

CREATE TABLE IF NOT EXISTS planet_mine_ascension_skills (
    planet_id INTEGER NOT NULL,
    building_type TEXT NOT NULL,
    skill_key TEXT NOT NULL,
    skill_rank INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, building_type, skill_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_planet_mine_ascension_skills_planet
    ON planet_mine_ascension_skills(planet_id);
