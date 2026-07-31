-- GC-CLASS-001 — Commander Classes & Skill Trees (EPIC-27)
-- Account-scoped class pick, linear skill trunk, SP milestones, swap audit.

CREATE TABLE IF NOT EXISTS player_commander (
    player_id INTEGER PRIMARY KEY,
    class_key TEXT,
    chosen_at REAL,
    swap_count INTEGER NOT NULL DEFAULT 0,
    skill_points_unspent INTEGER NOT NULL DEFAULT 0,
    skill_points_earned INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_commander_skills (
    player_id INTEGER NOT NULL,
    skill_key TEXT NOT NULL,
    rank INTEGER NOT NULL DEFAULT 0,
    unlocked_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, skill_key),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_commander_sp_claims (
    player_id INTEGER NOT NULL,
    milestone_key TEXT NOT NULL,
    claimed_at REAL NOT NULL DEFAULT 0,
    points_granted INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, milestone_key),
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_commander_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    detail_json TEXT,
    created_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_player_commander_events_player
    ON player_commander_events (player_id, created_at DESC);
