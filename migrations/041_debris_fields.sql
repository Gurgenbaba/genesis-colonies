-- 041_debris_fields.sql
-- Battlefield debris at galaxy coordinates (GC-508).

CREATE TABLE IF NOT EXISTS debris_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    galaxy INTEGER NOT NULL,
    system INTEGER NOT NULL,
    position INTEGER NOT NULL,
    metal REAL NOT NULL DEFAULT 0 CHECK(metal >= 0),
    crystal REAL NOT NULL DEFAULT 0 CHECK(crystal >= 0),
    updated_at INTEGER NOT NULL DEFAULT 0,
    UNIQUE(galaxy, system, position)
);

CREATE INDEX IF NOT EXISTS idx_debris_fields_coords
    ON debris_fields(galaxy, system, position);
