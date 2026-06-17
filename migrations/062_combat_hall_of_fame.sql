-- 062_combat_hall_of_fame.sql
-- GC-700A: Public Combat Hall of Fame (top battles by destroyed value).

CREATE TABLE IF NOT EXISTS combat_hall_of_fame (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fleet_id                INTEGER NOT NULL UNIQUE,
    attacker_player_id      INTEGER NOT NULL DEFAULT 0,
    defender_player_id      INTEGER NOT NULL DEFAULT 0,
    attacker_name           TEXT NOT NULL DEFAULT '',
    defender_name           TEXT NOT NULL DEFAULT '',
    target_planet_id        INTEGER,
    target_name             TEXT NOT NULL DEFAULT '',
    target_coords           TEXT NOT NULL DEFAULT '',
    winner                  TEXT NOT NULL DEFAULT '',
    rounds                  INTEGER NOT NULL DEFAULT 0,
    attacker_loss_score     INTEGER NOT NULL DEFAULT 0,
    defender_loss_score     INTEGER NOT NULL DEFAULT 0,
    total_destroyed_score   INTEGER NOT NULL DEFAULT 0,
    loot_json               TEXT NOT NULL DEFAULT '{}',
    debris_json             TEXT NOT NULL DEFAULT '{}',
    report_metadata_json    TEXT NOT NULL DEFAULT '{}',
    created_at              INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_combat_hof_score
    ON combat_hall_of_fame (total_destroyed_score DESC);

CREATE INDEX IF NOT EXISTS idx_combat_hof_created
    ON combat_hall_of_fame (created_at DESC);
