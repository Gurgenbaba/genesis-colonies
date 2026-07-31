-- 124_world_boss_tamed_status.sql
-- Allow status 'tamed' when a Phase-3 catch succeeds (boss leaves the map).

PRAGMA foreign_keys = OFF;

CREATE TABLE IF NOT EXISTS world_boss_events_new (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    boss_key            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('scheduled', 'active', 'defeated', 'expired', 'tamed')),
    galaxy              INTEGER NOT NULL,
    system              INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    max_hp              INTEGER NOT NULL CHECK(max_hp > 0),
    current_hp          INTEGER NOT NULL CHECK(current_hp >= 0),
    phase_index         INTEGER NOT NULL DEFAULT 0,
    fleet_stacks_json   TEXT NOT NULL DEFAULT '{}',
    starts_at           REAL NOT NULL,
    ends_at             REAL NOT NULL,
    defeated_at         REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    discovered_by_player_id INTEGER,
    FOREIGN KEY(boss_key) REFERENCES world_boss_definitions(boss_key)
);

INSERT INTO world_boss_events_new (
    id, boss_key, status, galaxy, system, position,
    max_hp, current_hp, phase_index, fleet_stacks_json,
    starts_at, ends_at, defeated_at, created_at, updated_at,
    discovered_by_player_id
)
SELECT
    id, boss_key, status, galaxy, system, position,
    max_hp, current_hp, phase_index, fleet_stacks_json,
    starts_at, ends_at, defeated_at, created_at, updated_at,
    discovered_by_player_id
FROM world_boss_events;

DROP TABLE world_boss_events;

ALTER TABLE world_boss_events_new RENAME TO world_boss_events;

CREATE INDEX IF NOT EXISTS idx_world_boss_events_status
    ON world_boss_events(status, ends_at);

CREATE INDEX IF NOT EXISTS idx_world_boss_events_coords
    ON world_boss_events(galaxy, system, position);

PRAGMA foreign_keys = ON;
