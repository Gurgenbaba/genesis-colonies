-- GC-720B — Galactic Directives schema + definition seed (no voting / no gameplay hooks)

CREATE TABLE IF NOT EXISTS gd_directive_definitions (
    directive_key            TEXT PRIMARY KEY NOT NULL,
    label_key                TEXT NOT NULL,
    description_key          TEXT NOT NULL,
    mechanics_json           TEXT NOT NULL DEFAULT '{}',
    secondary_mechanics_json TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json           TEXT NOT NULL DEFAULT '{}',
    eligible_as              TEXT NOT NULL DEFAULT '["primary","secondary"]',
    sort_order               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_galaxy_state (
    galaxy                   INTEGER PRIMARY KEY NOT NULL,
    primary_directive        TEXT,
    secondary_directive      TEXT,
    primary_since            INTEGER,
    consecutive_primary_wins INTEGER NOT NULL DEFAULT 0,
    cooldown_directive       TEXT,
    cooldown_until_ym        TEXT,
    last_cycle_id            INTEGER,
    updated_at               INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_cycles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    galaxy                  INTEGER NOT NULL,
    year                    INTEGER NOT NULL,
    month                   INTEGER NOT NULL,
    vote_start_at           INTEGER NOT NULL,
    vote_end_at             INTEGER NOT NULL,
    effect_start_at         INTEGER NOT NULL,
    effect_end_at           INTEGER NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'vote_open',
    winning_primary         TEXT,
    winning_secondary       TEXT,
    winning_primary_votes   INTEGER NOT NULL DEFAULT 0,
    winning_secondary_votes INTEGER NOT NULL DEFAULT 0,
    total_votes             INTEGER NOT NULL DEFAULT 0,
    total_voters            INTEGER NOT NULL DEFAULT 0,
    is_tie_primary          INTEGER NOT NULL DEFAULT 0,
    is_tie_secondary        INTEGER NOT NULL DEFAULT 0,
    results_sent            INTEGER NOT NULL DEFAULT 0,
    created_at              INTEGER NOT NULL,
    updated_at              INTEGER NOT NULL,
    UNIQUE (galaxy, year, month)
);

CREATE TABLE IF NOT EXISTS gd_votes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        INTEGER NOT NULL,
    galaxy          INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    directive_key   TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    UNIQUE (cycle_id, player_id),
    FOREIGN KEY (cycle_id) REFERENCES gd_cycles(id),
    FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_gd_cycles_galaxy_status ON gd_cycles(galaxy, status);
CREATE INDEX IF NOT EXISTS idx_gd_votes_cycle_id ON gd_votes(cycle_id);
CREATE INDEX IF NOT EXISTS idx_gd_votes_galaxy ON gd_votes(galaxy);

-- Core directive definitions (see docs/GALACTIC_DIRECTIVES.md)
INSERT OR IGNORE INTO gd_directive_definitions (
    directive_key, label_key, description_key,
    mechanics_json, secondary_mechanics_json, tradeoffs_json,
    eligible_as, sort_order
) VALUES
(
    'industrial',
    'gd_dir_industrial_title',
    'gd_dir_industrial_desc',
    '{"effect_resolver":{"metal_prod_factor":1.20,"crystal_prod_factor":1.15,"fuel_prod_factor":1.25,"storage_factor":1.10,"build_time_speed":1.176,"mine_energy_factor":1.20},"flags":{"planet_research_speed_bonus":-0.05}}',
    '{"effect_resolver":{"metal_prod_factor":1.08,"crystal_prod_factor":1.06,"fuel_prod_factor":1.10,"storage_factor":1.04}}',
    '{"effect_resolver":{"mine_energy_factor":1.20},"flags":{"planet_research_speed_bonus":-0.05}}',
    '["primary","secondary"]',
    10
),
(
    'scientific',
    'gd_dir_scientific_title',
    'gd_dir_scientific_desc',
    '{"effect_resolver":{"research_time_speed":1.25,"fleet_speed_multiplier":1.10,"weapon_bonus":-0.15},"queue_limits":{"research":1},"flags":{"planet_research_speed_bonus":0.10,"discovery_roll_bonus":0.15}}',
    '{"effect_resolver":{"research_time_speed":1.10},"flags":{"planet_research_speed_bonus":0.05}}',
    '{"effect_resolver":{"weapon_bonus":-0.15}}',
    '["primary","secondary"]',
    20
),
(
    'military',
    'gd_dir_military_title',
    'gd_dir_military_desc',
    '{"effect_resolver":{"weapon_bonus":0.20,"shield_bonus":0.15,"armor_bonus":0.10,"shipyard_time_speed":1.25,"defense_time_speed":1.25,"research_time_speed":0.80,"metal_prod_factor":0.90,"crystal_prod_factor":0.90,"fuel_prod_factor":0.90}}',
    '{"effect_resolver":{"weapon_bonus":0.08,"shield_bonus":0.08,"shipyard_time_speed":1.10}}',
    '{"effect_resolver":{"research_time_speed":0.80,"metal_prod_factor":0.90,"crystal_prod_factor":0.90,"fuel_prod_factor":0.90}}',
    '["primary","secondary"]',
    30
),
(
    'logistics',
    'gd_dir_logistics_title',
    'gd_dir_logistics_desc',
    '{"effect_resolver":{"cargo_multiplier":1.50,"fleet_speed_multiplier":1.20,"fuel_efficiency_factor":0.75,"solar_output_factor":0.95},"flags":{"trader_daily_limit_mult":1.50,"scrapyard_yield_mult":1.20,"trade_route_speed_mult":1.25}}',
    '{"effect_resolver":{"cargo_multiplier":1.20,"fleet_speed_multiplier":1.10,"fuel_efficiency_factor":0.90}}',
    '{"effect_resolver":{"solar_output_factor":0.95}}',
    '["primary","secondary"]',
    40
),
(
    'defensive',
    'gd_dir_defensive_title',
    'gd_dir_defensive_desc',
    '{"effect_resolver":{"shield_bonus":0.15,"armor_bonus":0.10,"defense_time_speed":1.10,"shipyard_time_speed":0.95,"fleet_speed_multiplier":0.95},"flags":{"defense_combat_mult":0.10}}',
    '{"effect_resolver":{"shield_bonus":0.06,"defense_time_speed":1.05}}',
    '{"effect_resolver":{"shipyard_time_speed":0.95,"fleet_speed_multiplier":0.95}}',
    '["primary","secondary"]',
    50
),
(
    'expansion',
    'gd_dir_expansion_title',
    'gd_dir_expansion_desc',
    '{"effect_resolver":{"build_time_speed":1.10,"storage_factor":1.10,"research_time_speed":0.95},"flags":{"max_colonies_bonus":1,"colonize_cost_mult":0.70,"planet_xp_mult":1.50,"planet_xp_mult_cap_level":10},"unlocks":["unlock:expansion_site:frontier_gate_discount","unlock:world:expansion_pool_bonus"]}',
    '{"flags":{"colonize_cost_mult":0.85},"effect_resolver":{"storage_factor":1.05}}',
    '{"effect_resolver":{"research_time_speed":0.95}}',
    '["primary","secondary"]',
    60
),
(
    'exploration',
    'gd_dir_exploration_title',
    'gd_dir_exploration_desc',
    '{"effect_resolver":{"metal_prod_factor":0.95},"flags":{"expedition_loot_mult":2.00,"expedition_event_bonus":0.30,"expedition_wreckage_bonus":0.25,"expedition_legendary_bonus":0.10,"expedition_slot_bonus":1},"unlocks":["unlock:world:anomaly_pool_extended","unlock:world:legendary_sites_teaser"]}',
    '{"flags":{"expedition_loot_mult":1.40,"expedition_event_bonus":0.10}}',
    '{"effect_resolver":{"metal_prod_factor":0.95}}',
    '["primary","secondary"]',
    70
);
