-- GC-721B — Galactic Diplomacy schema + definition seeds (no effects / no voting)

CREATE TABLE IF NOT EXISTS gd_bloc_definitions (
    bloc_key                 TEXT PRIMARY KEY NOT NULL,
    label_key                TEXT NOT NULL,
    description_key          TEXT NOT NULL,
    affinity_directives_json TEXT NOT NULL DEFAULT '[]',
    sort_order               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_alliance_blocs (
    alliance_id     INTEGER NOT NULL,
    galaxy          INTEGER NOT NULL,
    bloc_key        TEXT NOT NULL,
    since_at        INTEGER NOT NULL DEFAULT 0,
    cooldown_until  INTEGER,
    updated_at      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (alliance_id, galaxy),
    FOREIGN KEY (bloc_key) REFERENCES gd_bloc_definitions(bloc_key)
);

CREATE INDEX IF NOT EXISTS idx_gd_alliance_blocs_galaxy ON gd_alliance_blocs(galaxy);
CREATE INDEX IF NOT EXISTS idx_gd_alliance_blocs_bloc ON gd_alliance_blocs(bloc_key);

CREATE TABLE IF NOT EXISTS gd_resolution_definitions (
    resolution_type     TEXT PRIMARY KEY NOT NULL,
    label_key           TEXT NOT NULL,
    description_key     TEXT NOT NULL,
    payload_schema_json TEXT NOT NULL DEFAULT '{}',
    sort_order          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_emergency_definitions (
    emergency_key    TEXT PRIMARY KEY NOT NULL,
    label_key        TEXT NOT NULL,
    description_key  TEXT NOT NULL,
    mechanics_json   TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json   TEXT NOT NULL DEFAULT '{}',
    duration_days    INTEGER NOT NULL DEFAULT 30,
    sort_order       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_galaxy_personality_definitions (
    personality_key   TEXT PRIMARY KEY NOT NULL,
    label_key         TEXT NOT NULL,
    description_key   TEXT NOT NULL,
    mechanics_json    TEXT NOT NULL DEFAULT '{}',
    unlock_rules_json TEXT NOT NULL DEFAULT '{}',
    sort_order        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_galaxy_personality_state (
    galaxy          INTEGER PRIMARY KEY NOT NULL,
    personality_key TEXT,
    score_json      TEXT NOT NULL DEFAULT '{}',
    active_since    INTEGER,
    updated_at      INTEGER NOT NULL DEFAULT 0
);

-- Alliance blocs (GC-721C assignment)
INSERT OR IGNORE INTO gd_bloc_definitions (
    bloc_key, label_key, description_key, affinity_directives_json, sort_order
) VALUES
(
    'scientific_bloc',
    'gdp_bloc_scientific_title',
    'gdp_bloc_scientific_desc',
    '["scientific","exploration"]',
    10
),
(
    'military_bloc',
    'gdp_bloc_military_title',
    'gdp_bloc_military_desc',
    '["military","defensive"]',
    20
),
(
    'industrial_bloc',
    'gdp_bloc_industrial_title',
    'gdp_bloc_industrial_desc',
    '["industrial","logistics"]',
    30
),
(
    'frontier_bloc',
    'gdp_bloc_frontier_title',
    'gdp_bloc_frontier_desc',
    '["expansion","exploration"]',
    40
),
(
    'neutral_bloc',
    'gdp_bloc_neutral_title',
    'gdp_bloc_neutral_desc',
    '[]',
    50
);

-- Galaxy personality traits (GC-721D scorer — definitions only here)
INSERT OR IGNORE INTO gd_galaxy_personality_definitions (
    personality_key, label_key, description_key, mechanics_json, unlock_rules_json, sort_order
) VALUES
(
    'academia_prime',
    'gdp_trait_academia_prime_title',
    'gdp_trait_academia_prime_desc',
    '{"effect_resolver":{"research_time_speed":1.10}}',
    '{"min_wins":4,"window_cycles":6,"directive_keys":["scientific"]}',
    10
),
(
    'forge_of_war',
    'gdp_trait_forge_of_war_title',
    'gdp_trait_forge_of_war_desc',
    '{"effect_resolver":{"weapon_bonus":0.05,"shipyard_time_speed":1.05}}',
    '{"min_wins":3,"window_cycles":6,"directive_keys":["military","industrial"]}',
    20
),
(
    'frontier_space',
    'gdp_trait_frontier_space_title',
    'gdp_trait_frontier_space_desc',
    '{"flags":{"expedition_loot_mult":1.10}}',
    '{"min_wins":3,"window_cycles":6,"directive_keys":["exploration","expansion"]}',
    30
),
(
    'trade_nexus',
    'gdp_trait_trade_nexus_title',
    'gdp_trait_trade_nexus_desc',
    '{"effect_resolver":{"cargo_multiplier":1.10},"flags":{"trader_daily_limit_mult":1.10}}',
    '{"min_wins":3,"window_cycles":6,"directive_keys":["logistics"]}',
    40
),
(
    'bastion_sector',
    'gdp_trait_bastion_sector_title',
    'gdp_trait_bastion_sector_desc',
    '{"effect_resolver":{"shield_bonus":0.05,"defense_time_speed":1.05}}',
    '{"min_wins":3,"window_cycles":6,"directive_keys":["defensive"]}',
    50
);
