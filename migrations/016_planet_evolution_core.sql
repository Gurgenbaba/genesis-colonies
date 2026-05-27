-- Planet Evolution System — core schema (mechanics-only, no visuals)

ALTER TABLE planets ADD COLUMN galaxy INTEGER NOT NULL DEFAULT 1;
ALTER TABLE planets ADD COLUMN system INTEGER;
ALTER TABLE planets ADD COLUMN position INTEGER;
ALTER TABLE planets ADD COLUMN planet_class TEXT NOT NULL DEFAULT 'terrestrial';
ALTER TABLE planets ADD COLUMN planet_level INTEGER NOT NULL DEFAULT 1;
ALTER TABLE planets ADD COLUMN planet_xp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN specialization_key TEXT;
ALTER TABLE planets ADD COLUMN specialization_tier INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN ascension_key TEXT;
ALTER TABLE planets ADD COLUMN ascension_rank INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN culture_archetype TEXT NOT NULL DEFAULT 'frontier_settlers';
ALTER TABLE planets ADD COLUMN dna_seed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN dna_reveal_tier INTEGER NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN event_cooldown_until REAL NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN failure_state TEXT;
ALTER TABLE planets ADD COLUMN created_at REAL NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN last_evolution_tick REAL NOT NULL DEFAULT 0;

ALTER TABLE players ADD COLUMN active_planet_id INTEGER;

CREATE TABLE IF NOT EXISTS planet_dna (
    planet_id INTEGER PRIMARY KEY,
    rarity_tier TEXT NOT NULL DEFAULT 'common',
    geology_traits_json TEXT NOT NULL DEFAULT '[]',
    atmosphere_traits_json TEXT NOT NULL DEFAULT '[]',
    environment_traits_json TEXT NOT NULL DEFAULT '[]',
    anomaly_traits_json TEXT NOT NULL DEFAULT '[]',
    hidden_traits_json TEXT NOT NULL DEFAULT '[]',
    affinity_scores_json TEXT NOT NULL DEFAULT '{}',
    risk_profile_json TEXT NOT NULL DEFAULT '{}',
    resource_potential_json TEXT NOT NULL DEFAULT '{}',
    generated_at REAL NOT NULL,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_mechanics (
    planet_id INTEGER PRIMARY KEY,
    unlocks_json TEXT NOT NULL DEFAULT '[]',
    flags_json TEXT NOT NULL DEFAULT '{}',
    export_slots_json TEXT NOT NULL DEFAULT '[]',
    queue_limits_json TEXT NOT NULL DEFAULT '{}',
    risk_modifiers_json TEXT NOT NULL DEFAULT '{}',
    compiled_at REAL NOT NULL,
    compile_version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_research_levels (
    planet_id INTEGER NOT NULL,
    tech_key TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 0,
    unlocked_at REAL,
    PRIMARY KEY (planet_id, tech_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_research_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    tech_key TEXT NOT NULL,
    target_level INTEGER NOT NULL DEFAULT 1,
    start_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    request_id TEXT,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_planet_research_queue_planet_finish
    ON planet_research_queue(planet_id, finish_at);

CREATE TABLE IF NOT EXISTS planet_locked_choices (
    planet_id INTEGER NOT NULL,
    choice_group TEXT NOT NULL,
    choice_key TEXT NOT NULL,
    chosen_at REAL NOT NULL,
    PRIMARY KEY (planet_id, choice_group),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_policies (
    planet_id INTEGER NOT NULL,
    slot INTEGER NOT NULL,
    policy_key TEXT NOT NULL,
    activated_at REAL NOT NULL,
    cooldown_until REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, slot),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_culture (
    planet_id INTEGER PRIMARY KEY,
    archetype_key TEXT NOT NULL DEFAULT 'frontier_settlers',
    stability REAL NOT NULL DEFAULT 70.0,
    loyalty REAL NOT NULL DEFAULT 80.0,
    prosperity REAL NOT NULL DEFAULT 50.0,
    militarization REAL NOT NULL DEFAULT 20.0,
    science_focus REAL NOT NULL DEFAULT 30.0,
    crime REAL NOT NULL DEFAULT 10.0,
    industrial_pressure REAL NOT NULL DEFAULT 25.0,
    last_drift_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_special_resources (
    planet_id INTEGER NOT NULL,
    resource_key TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    cap REAL NOT NULL DEFAULT 100000,
    production_per_hour REAL NOT NULL DEFAULT 0,
    consumption_per_hour REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id, resource_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_production_chains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    chain_key TEXT NOT NULL,
    building_key TEXT NOT NULL DEFAULT 'virtual',
    is_active INTEGER NOT NULL DEFAULT 1,
    efficiency REAL NOT NULL DEFAULT 1.0,
    last_tick_at REAL NOT NULL DEFAULT 0,
    UNIQUE(planet_id, chain_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_conversion_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    chain_key TEXT NOT NULL,
    batches INTEGER NOT NULL DEFAULT 1,
    start_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    request_id TEXT,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_planet_conversion_queue_planet_finish
    ON planet_conversion_queue(planet_id, finish_at);

CREATE TABLE IF NOT EXISTS planet_trade_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_player_id INTEGER NOT NULL,
    source_planet_id INTEGER NOT NULL,
    target_planet_id INTEGER NOT NULL,
    resource_key TEXT NOT NULL,
    amount_per_hour REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    FOREIGN KEY (owner_player_id) REFERENCES players(id) ON DELETE CASCADE,
    FOREIGN KEY (source_planet_id) REFERENCES planets(id) ON DELETE CASCADE,
    FOREIGN KEY (target_planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_trade_routes_owner ON planet_trade_routes(owner_player_id, is_active);

CREATE TABLE IF NOT EXISTS planet_import_demands (
    planet_id INTEGER NOT NULL,
    resource_key TEXT NOT NULL,
    required_per_hour REAL NOT NULL DEFAULT 0,
    deficit_penalty_key TEXT NOT NULL DEFAULT 'chain_efficiency_halved',
    PRIMARY KEY (planet_id, resource_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    event_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    severity TEXT NOT NULL DEFAULT 'normal',
    started_at REAL NOT NULL,
    resolve_by REAL,
    player_choice_key TEXT,
    outcome_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_planet_events_active ON planet_events(planet_id, state);

CREATE TABLE IF NOT EXISTS planet_discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    discovery_key TEXT NOT NULL,
    rarity TEXT NOT NULL,
    discovered_at REAL NOT NULL,
    announced_globally INTEGER NOT NULL DEFAULT 0,
    effects_applied_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(planet_id, discovery_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_failure_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    failure_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'active',
    started_at REAL NOT NULL,
    resolve_at REAL,
    effects_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_planet_failures_active ON planet_failure_states(planet_id, state);

CREATE TABLE IF NOT EXISTS planet_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    history_tag TEXT,
    title_key TEXT NOT NULL,
    body_key TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    visibility TEXT NOT NULL DEFAULT 'owner',
    created_at REAL NOT NULL,
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_planet_history_planet ON planet_history(planet_id, created_at DESC);

CREATE TABLE IF NOT EXISTS planet_legacy_tags (
    planet_id INTEGER NOT NULL,
    tag_key TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    first_at REAL NOT NULL,
    last_at REAL NOT NULL,
    PRIMARY KEY (planet_id, tag_key),
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS planet_ascension_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    planet_id INTEGER NOT NULL UNIQUE,
    ascension_key TEXT NOT NULL,
    start_at REAL NOT NULL,
    finish_at REAL NOT NULL,
    quest_stage INTEGER NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'active',
    FOREIGN KEY (planet_id) REFERENCES planets(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pe_trait_definitions (
    trait_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    rarity TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    planet_class_weights_json TEXT NOT NULL DEFAULT '{}',
    effects_json TEXT NOT NULL DEFAULT '{}',
    unlocks_json TEXT NOT NULL DEFAULT '[]',
    blocks_json TEXT NOT NULL DEFAULT '[]',
    risk_json TEXT NOT NULL DEFAULT '{}',
    lore_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_research_definitions (
    tech_key TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    tier INTEGER NOT NULL DEFAULT 1,
    max_level INTEGER NOT NULL DEFAULT 1,
    base_cost_m INTEGER NOT NULL DEFAULT 0,
    base_cost_c INTEGER NOT NULL DEFAULT 0,
    base_time REAL NOT NULL DEFAULT 600,
    cost_factor REAL NOT NULL DEFAULT 1.6,
    requirements_json TEXT NOT NULL DEFAULT '{}',
    choice_group TEXT,
    choice_options_json TEXT,
    mechanics_json TEXT NOT NULL DEFAULT '{}',
    risk_json TEXT NOT NULL DEFAULT '{}',
    label_key TEXT NOT NULL,
    description_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_specialization_definitions (
    spec_key TEXT PRIMARY KEY,
    required_traits_any_json TEXT NOT NULL DEFAULT '[]',
    required_affinities_json TEXT NOT NULL DEFAULT '{}',
    min_planet_level INTEGER NOT NULL DEFAULT 8,
    incompatible_specs_json TEXT NOT NULL DEFAULT '[]',
    tier_mechanics_json TEXT NOT NULL DEFAULT '{}',
    event_pool_json TEXT NOT NULL DEFAULT '[]',
    export_unlocks_json TEXT NOT NULL DEFAULT '[]',
    import_demands_json TEXT NOT NULL DEFAULT '[]',
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_policy_definitions (
    policy_key TEXT PRIMARY KEY,
    tier INTEGER NOT NULL DEFAULT 1,
    archetype_allow_json TEXT NOT NULL DEFAULT '[]',
    mechanics_json TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json TEXT NOT NULL DEFAULT '{}',
    cooldown_hours REAL NOT NULL DEFAULT 72,
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_event_definitions (
    event_key TEXT PRIMARY KEY,
    pool_tags_json TEXT NOT NULL DEFAULT '[]',
    severity TEXT NOT NULL DEFAULT 'normal',
    trigger_json TEXT NOT NULL DEFAULT '{}',
    choices_json TEXT NOT NULL DEFAULT '[]',
    failure_link_json TEXT,
    history_tag TEXT,
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_discovery_definitions (
    discovery_key TEXT PRIMARY KEY,
    rarity TEXT NOT NULL,
    roll_weight REAL NOT NULL DEFAULT 0,
    requirements_json TEXT NOT NULL DEFAULT '{}',
    mechanics_json TEXT NOT NULL DEFAULT '{}',
    announce_global INTEGER NOT NULL DEFAULT 0,
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_special_resource_definitions (
    resource_key TEXT PRIMARY KEY,
    base_cap REAL NOT NULL DEFAULT 100000,
    tradeable INTEGER NOT NULL DEFAULT 1,
    decay_per_day REAL NOT NULL DEFAULT 0,
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_production_chain_definitions (
    chain_key TEXT PRIMARY KEY,
    output_resource_key TEXT NOT NULL,
    inputs_json TEXT NOT NULL DEFAULT '{}',
    base_output_per_hour REAL NOT NULL DEFAULT 0,
    required_building TEXT NOT NULL DEFAULT 'virtual',
    required_unlock TEXT NOT NULL,
    failure_risk_json TEXT NOT NULL DEFAULT '{}',
    label_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pe_ascension_definitions (
    ascension_key TEXT PRIMARY KEY,
    requirements_json TEXT NOT NULL DEFAULT '{}',
    permanent_mechanics_json TEXT NOT NULL DEFAULT '{}',
    duration_days REAL NOT NULL DEFAULT 7,
    label_key TEXT NOT NULL
);

UPDATE planets SET created_at = strftime('%s','now') WHERE created_at = 0 OR created_at IS NULL;
UPDATE planets SET last_evolution_tick = strftime('%s','now') WHERE last_evolution_tick = 0 OR last_evolution_tick IS NULL;

ALTER TABLE player_scores ADD COLUMN score_planet_evolution INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_scores ADD COLUMN rank_planet_evolution INTEGER;
