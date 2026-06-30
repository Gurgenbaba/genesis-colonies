-- 088_alliance_hub.sql
-- EPIC-09 Alliance Hub MVP (GC-AL-001 … GC-AL-006)

-- Extend alliances
ALTER TABLE alliances ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE alliances ADD COLUMN alliance_level INTEGER NOT NULL DEFAULT 1;
ALTER TABLE alliances ADD COLUMN alliance_xp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alliances ADD COLUMN pool_metal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alliances ADD COLUMN pool_crystal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alliances ADD COLUMN pool_fuel_cells INTEGER NOT NULL DEFAULT 0;
ALTER TABLE alliances ADD COLUMN member_limit INTEGER NOT NULL DEFAULT 5;

-- Canonical ranks: leader, officer, member (legacy owner → leader)
UPDATE alliance_members SET role = 'leader' WHERE role = 'owner';

CREATE TABLE IF NOT EXISTS alliance_donations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alliance_id INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    resource    TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    xp_granted  INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alliance_donations_alliance ON alliance_donations(alliance_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alliance_donations_player ON alliance_donations(player_id, created_at DESC);

CREATE TABLE IF NOT EXISTS alliance_buildings (
    alliance_id  INTEGER NOT NULL,
    building_key TEXT NOT NULL,
    level        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (alliance_id, building_key),
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alliance_technologies (
    alliance_id INTEGER NOT NULL,
    tech_key    TEXT NOT NULL,
    level       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (alliance_id, tech_key),
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alliance_projects (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    alliance_id    INTEGER NOT NULL,
    project_kind   TEXT NOT NULL,
    target_key     TEXT NOT NULL,
    target_level   INTEGER NOT NULL,
    status         TEXT NOT NULL DEFAULT 'active',
    started_at     INTEGER NOT NULL,
    finish_at      INTEGER NOT NULL,
    cost_metal     INTEGER NOT NULL DEFAULT 0,
    cost_crystal   INTEGER NOT NULL DEFAULT 0,
    cost_fuel_cells INTEGER NOT NULL DEFAULT 0,
    created_by     INTEGER,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(created_by) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_alliance_projects_active ON alliance_projects(alliance_id, status, finish_at);

CREATE TABLE IF NOT EXISTS alliance_applications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    alliance_id INTEGER NOT NULL,
    player_id   INTEGER NOT NULL,
    message     TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  INTEGER NOT NULL,
    responded_at INTEGER,
    FOREIGN KEY(alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alliance_applications_pending
    ON alliance_applications(alliance_id, player_id)
    WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS alliance_diplomacy (
    alliance_id_low  INTEGER NOT NULL,
    alliance_id_high INTEGER NOT NULL,
    relation         TEXT NOT NULL DEFAULT 'neutral',
    updated_at       INTEGER NOT NULL,
    PRIMARY KEY (alliance_id_low, alliance_id_high),
    FOREIGN KEY(alliance_id_low) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(alliance_id_high) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alliance_diplomacy_requests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    from_alliance_id INTEGER NOT NULL,
    to_alliance_id   INTEGER NOT NULL,
    request_type     TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    created_at       INTEGER NOT NULL,
    responded_at     INTEGER,
    responded_by     INTEGER,
    FOREIGN KEY(from_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(to_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(responded_by) REFERENCES players(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_alliance_diplomacy_req_to ON alliance_diplomacy_requests(to_alliance_id, status);
