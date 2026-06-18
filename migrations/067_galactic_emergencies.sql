-- GC-721F — Emergency directive definitions (expanded schema) + active state

DROP TABLE IF EXISTS gd_emergency_definitions;

CREATE TABLE gd_emergency_definitions (
    emergency_key   TEXT PRIMARY KEY NOT NULL,
    label_key       TEXT NOT NULL,
    description_key TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'crisis',
    mechanics_json  TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json  TEXT NOT NULL DEFAULT '{}',
    duration_days   INTEGER NOT NULL DEFAULT 30,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_emergency_state (
    galaxy        INTEGER PRIMARY KEY NOT NULL,
    emergency_key TEXT NOT NULL,
    payload_json  TEXT NOT NULL DEFAULT '{}',
    started_at    INTEGER NOT NULL,
    ends_at       INTEGER,
    updated_at    INTEGER NOT NULL,
    FOREIGN KEY (emergency_key) REFERENCES gd_emergency_definitions(emergency_key)
);

CREATE INDEX IF NOT EXISTS idx_gd_emergency_state_key ON gd_emergency_state(emergency_key);

INSERT OR IGNORE INTO gd_emergency_definitions (
    emergency_key, label_key, description_key, category,
    mechanics_json, tradeoffs_json, duration_days, sort_order
) VALUES
(
    'alien_invasion',
    'gdp_emergency_alien_invasion_title',
    'gdp_emergency_alien_invasion_desc',
    'invasion',
    '{"effect_resolver":{"weapon_bonus":0.25,"shield_bonus":0.20,"defense_time_speed":1.15},"flags":{"defense_combat_mult":0.10}}',
    '{"effect_resolver":{"metal_prod_factor":0.90,"crystal_prod_factor":0.90}}',
    30,
    10
),
(
    'galaxy_war',
    'gdp_emergency_galaxy_war_title',
    'gdp_emergency_galaxy_war_desc',
    'war',
    '{"effect_resolver":{"weapon_bonus":0.35,"shipyard_time_speed":1.20,"research_time_speed":0.80,"metal_prod_factor":0.85,"crystal_prod_factor":0.85},"flags":{"fleet_attack_bonus":0.10}}',
    '{"effect_resolver":{"research_time_speed":0.80,"metal_prod_factor":0.85,"crystal_prod_factor":0.85}}',
    30,
    20
),
(
    'resource_crisis',
    'gdp_emergency_resource_crisis_title',
    'gdp_emergency_resource_crisis_desc',
    'economy',
    '{"effect_resolver":{"metal_prod_factor":1.25,"crystal_prod_factor":1.20,"fuel_prod_factor":1.30,"build_time_speed":1.10},"flags":{"trader_daily_limit_mult":1.25}}',
    '{"effect_resolver":{"research_time_speed":0.85,"fleet_speed_multiplier":0.90}}',
    21,
    30
),
(
    'hyperstorm',
    'gdp_emergency_hyperstorm_title',
    'gdp_emergency_hyperstorm_desc',
    'environment',
    '{"effect_resolver":{"fleet_speed_multiplier":0.75,"solar_output_factor":0.80,"shield_bonus":0.10},"flags":{"expedition_event_bonus":-0.15}}',
    '{"effect_resolver":{"metal_prod_factor":0.95}}',
    14,
    40
),
(
    'frontier_collapse',
    'gdp_emergency_frontier_collapse_title',
    'gdp_emergency_frontier_collapse_desc',
    'frontier',
    '{"flags":{"colonize_cost_mult":0.60,"expedition_loot_mult":1.50,"max_colonies_bonus":0},"effect_resolver":{"build_time_speed":1.15,"storage_factor":1.10}}',
    '{"effect_resolver":{"weapon_bonus":-0.05}}',
    30,
    50
);
