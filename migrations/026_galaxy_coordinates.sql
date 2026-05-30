-- Galaxy coordinate uniqueness (active planets with assigned slots)

CREATE UNIQUE INDEX IF NOT EXISTS idx_planets_galaxy_system_position
    ON planets(galaxy, system, position)
    WHERE system IS NOT NULL AND position IS NOT NULL;
