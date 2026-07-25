-- 107_pirate_ecosystem.sql
-- EPIC-21 / GC-P01: Galaxy Heat, pirate factions/bases, threat, intel, action log.

CREATE TABLE IF NOT EXISTS galaxy_heat (
    galaxy_id       INTEGER PRIMARY KEY,
    heat            INTEGER NOT NULL DEFAULT 0 CHECK(heat >= 0 AND heat <= 1000),
    combat_events   INTEGER NOT NULL DEFAULT 0,
    expo_events     INTEGER NOT NULL DEFAULT 0,
    asteroid_events INTEGER NOT NULL DEFAULT 0,
    boss_events     INTEGER NOT NULL DEFAULT 0,
    colonize_events INTEGER NOT NULL DEFAULT 0,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS pirate_faction_defs (
    faction_key         TEXT PRIMARY KEY,
    name_key            TEXT NOT NULL,
    description_key     TEXT NOT NULL DEFAULT '',
    commander_key       TEXT NOT NULL DEFAULT '',
    aggression_weight   INTEGER NOT NULL DEFAULT 50 CHECK(aggression_weight >= 0),
    loot_tier           TEXT NOT NULL DEFAULT 'medium',
    defense_tier        TEXT NOT NULL DEFAULT 'medium',
    fleet_stacks_json   TEXT NOT NULL DEFAULT '{}',
    personality_json    TEXT NOT NULL DEFAULT '{}',
    sort_order          INTEGER NOT NULL DEFAULT 0,
    active              INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS pirate_bases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    faction_key         TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'escalating', 'destroyed', 'expired')),
    galaxy              INTEGER NOT NULL,
    system              INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    strength            INTEGER NOT NULL DEFAULT 1 CHECK(strength >= 1 AND strength <= 5),
    activity            INTEGER NOT NULL DEFAULT 0 CHECK(activity >= 0 AND activity <= 100),
    loot_tier           TEXT NOT NULL DEFAULT 'medium',
    fleet_stacks_json   TEXT NOT NULL DEFAULT '{}',
    max_hp              INTEGER NOT NULL DEFAULT 100 CHECK(max_hp > 0),
    current_hp          INTEGER NOT NULL DEFAULT 100 CHECK(current_hp >= 0),
    spawned_at          REAL NOT NULL,
    escalates_at        REAL,
    destroyed_at        REAL,
    expires_at          REAL,
    updated_at          REAL NOT NULL,
    FOREIGN KEY(faction_key) REFERENCES pirate_faction_defs(faction_key)
);

CREATE INDEX IF NOT EXISTS idx_pirate_bases_status
    ON pirate_bases(status, galaxy);

CREATE INDEX IF NOT EXISTS idx_pirate_bases_coords
    ON pirate_bases(galaxy, system, position);

CREATE TABLE IF NOT EXISTS pirate_base_contributions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    base_id             INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    alliance_id         INTEGER,
    damage              INTEGER NOT NULL DEFAULT 0 CHECK(damage >= 0),
    waves               INTEGER NOT NULL DEFAULT 0 CHECK(waves >= 0),
    last_attack_at      REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    UNIQUE(base_id, player_id),
    FOREIGN KEY(base_id) REFERENCES pirate_bases(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pirate_base_contrib_damage
    ON pirate_base_contributions(base_id, damage DESC);

CREATE TABLE IF NOT EXISTS pirate_base_claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    base_id             INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    tier_key            TEXT NOT NULL,
    claimed_at          REAL NOT NULL,
    UNIQUE(base_id, player_id, tier_key),
    FOREIGN KEY(base_id) REFERENCES pirate_bases(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_threat (
    player_id           INTEGER PRIMARY KEY,
    threat              INTEGER NOT NULL DEFAULT 0 CHECK(threat >= 0 AND threat <= 100),
    components_json     TEXT NOT NULL DEFAULT '{}',
    updated_at          REAL NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS player_bounty (
    player_id           INTEGER NOT NULL,
    faction_key         TEXT NOT NULL,
    credits             INTEGER NOT NULL DEFAULT 0 CHECK(credits >= 0),
    kills               INTEGER NOT NULL DEFAULT 0 CHECK(kills >= 0),
    updated_at          REAL NOT NULL,
    PRIMARY KEY(player_id, faction_key),
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY(faction_key) REFERENCES pirate_faction_defs(faction_key)
);

CREATE TABLE IF NOT EXISTS pirate_intel (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_player_id       INTEGER NOT NULL,
    target_planet_id    INTEGER NOT NULL,
    target_player_id    INTEGER NOT NULL,
    galaxy              INTEGER NOT NULL,
    system              INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    resources_score     INTEGER NOT NULL DEFAULT 0,
    fleet_score         INTEGER NOT NULL DEFAULT 0,
    defense_score       INTEGER NOT NULL DEFAULT 0,
    opportunity         INTEGER NOT NULL DEFAULT 0 CHECK(opportunity >= 0 AND opportunity <= 100),
    report_read_at      REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    UNIQUE(bot_player_id, target_planet_id)
);

CREATE INDEX IF NOT EXISTS idx_pirate_intel_bot_opp
    ON pirate_intel(bot_player_id, opportunity DESC);

CREATE TABLE IF NOT EXISTS pirate_bot_state (
    bot_player_id       INTEGER PRIMARY KEY,
    faction_key         TEXT NOT NULL,
    personality         TEXT NOT NULL DEFAULT 'balanced',
    playtime_start_min  INTEGER NOT NULL DEFAULT 0,
    playtime_end_min    INTEGER NOT NULL DEFAULT 1440,
    skip_chance_pct     INTEGER NOT NULL DEFAULT 10,
    seed                INTEGER NOT NULL DEFAULT 0,
    next_action_at      REAL,
    mood_json           TEXT NOT NULL DEFAULT '{}',
    updated_at          REAL NOT NULL,
    FOREIGN KEY(faction_key) REFERENCES pirate_faction_defs(faction_key)
);

CREATE TABLE IF NOT EXISTS pirate_action_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  REAL NOT NULL,
    tick_id             TEXT,
    bot_player_id       INTEGER,
    faction_key         TEXT,
    base_id             INTEGER,
    galaxy_id           INTEGER,
    kind                TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'info'
                        CHECK(severity IN ('info', 'warn', 'error')),
    target_player_id    INTEGER,
    payload_json        TEXT NOT NULL DEFAULT '{}',
    message             TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_pirate_action_log_ts
    ON pirate_action_log(ts DESC);

CREATE INDEX IF NOT EXISTS idx_pirate_action_log_kind
    ON pirate_action_log(kind, ts DESC);

CREATE TABLE IF NOT EXISTS pirate_infiltrations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id           INTEGER NOT NULL,
    faction_key         TEXT NOT NULL,
    effect_key          TEXT NOT NULL,
    magnitude           REAL NOT NULL DEFAULT 0,
    started_at          REAL NOT NULL,
    expires_at          REAL NOT NULL,
    FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    FOREIGN KEY(faction_key) REFERENCES pirate_faction_defs(faction_key)
);

CREATE INDEX IF NOT EXISTS idx_pirate_infiltrations_expires
    ON pirate_infiltrations(expires_at);

CREATE TABLE IF NOT EXISTS smuggler_contacts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    galaxy              INTEGER NOT NULL,
    system              INTEGER NOT NULL,
    position            INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'raided', 'expired', 'rescued')),
    offer_json          TEXT NOT NULL DEFAULT '{}',
    spawned_at          REAL NOT NULL,
    expires_at          REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_smuggler_contacts_status
    ON smuggler_contacts(status, expires_at);

-- Seed four factions (GC-P01 catalog; stacks refined in GC-P09).
INSERT OR IGNORE INTO pirate_faction_defs (
    faction_key, name_key, description_key, commander_key,
    aggression_weight, loot_tier, defense_tier,
    fleet_stacks_json, personality_json, sort_order, active
) VALUES
(
    'crimson_corsairs',
    'pirate_faction_crimson_corsairs',
    'pirate_faction_crimson_corsairs_desc',
    'pirate_commander_crimson',
    80, 'high', 'low',
    '{"falcon_interceptor":40,"ironclad_frigate":20,"eclipse_runner":8}',
    '{"attack_bias":0.85,"spy_bias":0.55,"turtle":0.1}',
    10, 1
),
(
    'iron_collective',
    'pirate_faction_iron_collective',
    'pirate_faction_iron_collective_desc',
    'pirate_commander_iron',
    35, 'low', 'high',
    '{"ironclad_frigate":25,"eclipse_runner":12,"atlas_hauler":6}',
    '{"attack_bias":0.35,"spy_bias":0.3,"turtle":0.8}',
    20, 1
),
(
    'void_cult',
    'pirate_faction_void_cult',
    'pirate_faction_void_cult_desc',
    'pirate_commander_void',
    60, 'medium', 'medium',
    '{"veil_probe":30,"falcon_interceptor":25,"eclipse_runner":10}',
    '{"attack_bias":0.5,"spy_bias":0.9,"turtle":0.3}',
    30, 1
),
(
    'nomad_swarm',
    'pirate_faction_nomad_swarm',
    'pirate_faction_nomad_swarm_desc',
    'pirate_commander_nomad',
    70, 'medium', 'medium',
    '{"spark_drone":80,"falcon_interceptor":40,"ironclad_frigate":5}',
    '{"attack_bias":0.7,"spy_bias":0.4,"turtle":0.15}',
    40, 1
);
