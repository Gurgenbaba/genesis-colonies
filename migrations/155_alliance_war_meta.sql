-- 155_alliance_war_meta.sql
-- GC-AL-WAR-02: derived combat meta for active alliance wars.
-- Diplomacy lifecycle remains authoritative in alliance_diplomacy.

CREATE TABLE IF NOT EXISTS alliance_war_stats (
    alliance_id_low       INTEGER NOT NULL,
    alliance_id_high      INTEGER NOT NULL,
    war_started_at        INTEGER NOT NULL,
    low_score_raw         TEXT NOT NULL DEFAULT '0',
    high_score_raw        TEXT NOT NULL DEFAULT '0',
    low_units_destroyed   TEXT NOT NULL DEFAULT '0',
    high_units_destroyed  TEXT NOT NULL DEFAULT '0',
    low_wins              INTEGER NOT NULL DEFAULT 0,
    high_wins             INTEGER NOT NULL DEFAULT 0,
    draws                 INTEGER NOT NULL DEFAULT 0,
    battle_count          INTEGER NOT NULL DEFAULT 0,
    last_battle_at        INTEGER,
    updated_at            INTEGER NOT NULL,
    PRIMARY KEY (alliance_id_low, alliance_id_high),
    FOREIGN KEY(alliance_id_low) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(alliance_id_high) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alliance_war_events (
    fleet_id                 INTEGER PRIMARY KEY,
    alliance_id_low          INTEGER NOT NULL,
    alliance_id_high         INTEGER NOT NULL,
    war_started_at           INTEGER NOT NULL,
    attacker_alliance_id     INTEGER NOT NULL,
    defender_alliance_id     INTEGER NOT NULL,
    attacker_score_raw       TEXT NOT NULL DEFAULT '0',
    defender_score_raw       TEXT NOT NULL DEFAULT '0',
    attacker_units_destroyed TEXT NOT NULL DEFAULT '0',
    defender_units_destroyed TEXT NOT NULL DEFAULT '0',
    result                   TEXT NOT NULL,
    created_at               INTEGER NOT NULL,
    FOREIGN KEY(alliance_id_low) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(alliance_id_high) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(attacker_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(defender_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alliance_war_events_campaign
    ON alliance_war_events(alliance_id_low, alliance_id_high, war_started_at, created_at);
