-- GC-582A — World map colonization persistence (claims + planet world binding)

CREATE TABLE IF NOT EXISTS world_claims (
    world_key       TEXT PRIMARY KEY NOT NULL,
    player_id       INTEGER NOT NULL,
    planet_id       INTEGER,
    world_x         REAL NOT NULL,
    world_y         REAL NOT NULL,
    sector_x        INTEGER NOT NULL,
    sector_y        INTEGER NOT NULL,
    planet_role     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved', 'claimed')),
    reserved_at     REAL NOT NULL,
    claimed_at      REAL,
    FOREIGN KEY (player_id) REFERENCES players(id),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE INDEX IF NOT EXISTS idx_world_claims_player_id ON world_claims(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_world_claims_planet_id
    ON world_claims(planet_id)
    WHERE planet_id IS NOT NULL;

ALTER TABLE planets ADD COLUMN world_key TEXT;
ALTER TABLE planets ADD COLUMN world_x REAL;
ALTER TABLE planets ADD COLUMN world_y REAL;
ALTER TABLE planets ADD COLUMN sector_x INTEGER;
ALTER TABLE planets ADD COLUMN sector_y INTEGER;
ALTER TABLE planets ADD COLUMN planet_role TEXT;
ALTER TABLE planets ADD COLUMN origin_world_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_planets_world_key
    ON planets(world_key)
    WHERE world_key IS NOT NULL;
