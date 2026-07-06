-- Combat balance bot audit log (dev/admin live balance stand).

CREATE TABLE IF NOT EXISTS combat_balance_runs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_key         TEXT NOT NULL,
    attacker_bot_id      INTEGER NOT NULL,
    defender_bot_id      INTEGER NOT NULL,
    fleet_movement_id    INTEGER,
    started_at           INTEGER NOT NULL,
    resolved_at          INTEGER,
    attacker_setup_json  TEXT NOT NULL DEFAULT '{}',
    defender_setup_json  TEXT NOT NULL DEFAULT '{}',
    result_json          TEXT,
    winner               TEXT,
    rounds               INTEGER,
    attacker_losses_json TEXT,
    defender_losses_json TEXT,
    debris_json          TEXT,
    loot_json            TEXT,
    notes                TEXT,
    FOREIGN KEY(attacker_bot_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(defender_bot_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(fleet_movement_id) REFERENCES fleet_movements(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_combat_balance_runs_movement
    ON combat_balance_runs (fleet_movement_id);

CREATE INDEX IF NOT EXISTS idx_combat_balance_runs_started
    ON combat_balance_runs (started_at DESC);
