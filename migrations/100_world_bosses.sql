-- 100_world_bosses.sql
-- EPIC-20 / GC-W02: Server-wide PvE World Boss events (shared HP, contribution, claims).

CREATE TABLE IF NOT EXISTS world_boss_definitions (
    boss_key            TEXT PRIMARY KEY,
    name_key            TEXT NOT NULL,
    description_key     TEXT NOT NULL DEFAULT '',
    max_hp              INTEGER NOT NULL CHECK(max_hp > 0),
    duration_seconds    INTEGER NOT NULL DEFAULT 172800 CHECK(duration_seconds > 0),
    fleet_stacks_json   TEXT NOT NULL DEFAULT '{}',
    phases_json         TEXT NOT NULL DEFAULT '[]',
    loot_pool_key       TEXT NOT NULL DEFAULT 'container_event_special',
    spawn_weight        INTEGER NOT NULL DEFAULT 1 CHECK(spawn_weight >= 0),
    sort_order          INTEGER NOT NULL DEFAULT 0,
    active              INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS world_boss_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    boss_key            TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('scheduled', 'active', 'defeated', 'expired')),
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
    FOREIGN KEY(boss_key) REFERENCES world_boss_definitions(boss_key)
);

CREATE INDEX IF NOT EXISTS idx_world_boss_events_status
    ON world_boss_events(status, ends_at);

CREATE INDEX IF NOT EXISTS idx_world_boss_events_coords
    ON world_boss_events(galaxy, system, position);

CREATE TABLE IF NOT EXISTS world_boss_contributions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    alliance_id         INTEGER,
    damage              INTEGER NOT NULL DEFAULT 0 CHECK(damage >= 0),
    waves               INTEGER NOT NULL DEFAULT 0 CHECK(waves >= 0),
    last_attack_at      REAL,
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL,
    UNIQUE(event_id, player_id),
    FOREIGN KEY(event_id) REFERENCES world_boss_events(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_world_boss_contrib_event_damage
    ON world_boss_contributions(event_id, damage DESC);

CREATE INDEX IF NOT EXISTS idx_world_boss_contrib_alliance
    ON world_boss_contributions(event_id, alliance_id);

CREATE TABLE IF NOT EXISTS world_boss_claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    tiers_json          TEXT NOT NULL DEFAULT '[]',
    rewards_json        TEXT NOT NULL DEFAULT '[]',
    claimed_at          REAL NOT NULL,
    UNIQUE(event_id, player_id),
    FOREIGN KEY(event_id) REFERENCES world_boss_events(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

-- Catalog seed (GC-W02)
INSERT OR IGNORE INTO world_boss_definitions (
    boss_key, name_key, description_key, max_hp, duration_seconds,
    fleet_stacks_json, phases_json, loot_pool_key, spawn_weight, sort_order, active
) VALUES
(
    'ancient_leviathan',
    'wb_boss_ancient_leviathan',
    'wb_boss_ancient_leviathan_desc',
    5000000,
    172800,
    '{"falcon_interceptor":800,"ironclad_frigate":200,"eclipse_runner":40}',
    '[{"hp_ratio":1.0},{"hp_ratio":0.5},{"hp_ratio":0.2}]',
    'container_event_special',
    1,
    10,
    1
),
(
    'void_titan',
    'wb_boss_void_titan',
    'wb_boss_void_titan_desc',
    4000000,
    172800,
    '{"falcon_interceptor":1200,"ironclad_frigate":400,"eclipse_runner":80}',
    '[{"hp_ratio":1.0},{"hp_ratio":0.4}]',
    'container_void_artifact',
    1,
    20,
    1
),
(
    'planet_eater',
    'wb_boss_planet_eater',
    'wb_boss_planet_eater_desc',
    6000000,
    172800,
    '{"falcon_interceptor":600,"ironclad_frigate":300,"atlas_hauler":100,"eclipse_runner":50}',
    '[{"hp_ratio":1.0},{"hp_ratio":0.6},{"hp_ratio":0.3}]',
    'container_event_special',
    1,
    30,
    1
),
(
    'rogue_ai_nexus',
    'wb_boss_rogue_ai_nexus',
    'wb_boss_rogue_ai_nexus_desc',
    3500000,
    172800,
    '{"veil_probe":200,"falcon_interceptor":900,"ironclad_frigate":150,"eclipse_runner":120}',
    '[{"hp_ratio":1.0,"stacks":{"veil_probe":200,"falcon_interceptor":900}},{"hp_ratio":0.5,"stacks":{"ironclad_frigate":400,"eclipse_runner":200}}]',
    'container_ancient_relic',
    1,
    40,
    1
);

-- Imperial directive: deal world boss damage (GC-W08)
INSERT OR IGNORE INTO directive_definitions (
    key, category, cadence, objective_kind, base_target, scale_profile,
    weight, min_rarity, max_rarity, filters_json, title_key, description_key, sort_order
) VALUES (
    'deal_world_boss_damage',
    'military',
    'both',
    'accumulate',
    50000,
    'produce',
    6,
    'common',
    'epic',
    '{"source":"world_boss"}',
    'id_def_deal_world_boss_damage_title',
    'id_def_deal_world_boss_damage_desc',
    360
);
