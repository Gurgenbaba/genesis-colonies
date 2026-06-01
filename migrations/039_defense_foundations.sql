-- 039_defense_foundations.sql
-- Planet-scoped defense stock (GC-410). No combat resolver in this migration.

CREATE TABLE IF NOT EXISTS planet_defense (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    defense_key TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0 CHECK(amount >= 0),
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    UNIQUE(planet_id, defense_key)
);

CREATE INDEX IF NOT EXISTS idx_planet_defense_planet
    ON planet_defense(planet_id);
