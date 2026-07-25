-- 104_asteroid_fields.sql
-- GC-AST-01: Temporary galaxy asteroid belt fields (harvest via recycle / harvest_reclaimer).

CREATE TABLE IF NOT EXISTS asteroid_fields (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    asteroid_key            TEXT NOT NULL,
    galaxy                  INTEGER NOT NULL,
    system                  INTEGER NOT NULL,
    position                INTEGER NOT NULL,
    metal                   REAL NOT NULL DEFAULT 0 CHECK(metal >= 0),
    crystal                 REAL NOT NULL DEFAULT 0 CHECK(crystal >= 0),
    fuel_cells              REAL NOT NULL DEFAULT 0 CHECK(fuel_cells >= 0),
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK(status IN ('active', 'claimed', 'expired')),
    spawned_at              REAL NOT NULL,
    expires_at              REAL NOT NULL,
    claimed_at              REAL,
    claimed_by_player_id    INTEGER,
    FOREIGN KEY(claimed_by_player_id) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_asteroid_fields_status_expires
    ON asteroid_fields(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_asteroid_fields_coords
    ON asteroid_fields(galaxy, system, position);

CREATE INDEX IF NOT EXISTS idx_asteroid_fields_active_coords
    ON asteroid_fields(galaxy, system, position, status);
