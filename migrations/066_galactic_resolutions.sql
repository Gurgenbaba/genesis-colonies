-- GC-721E — Diplomatic resolution definitions (expanded schema) + active state

DROP TABLE IF EXISTS gd_resolution_definitions;

CREATE TABLE gd_resolution_definitions (
    resolution_key   TEXT PRIMARY KEY NOT NULL,
    label_key        TEXT NOT NULL,
    description_key  TEXT NOT NULL,
    category         TEXT NOT NULL DEFAULT 'general',
    mechanics_json   TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json   TEXT NOT NULL DEFAULT '{}',
    duration_days    INTEGER NOT NULL DEFAULT 30,
    sort_order       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS gd_resolution_state (
    galaxy         INTEGER PRIMARY KEY NOT NULL,
    resolution_key TEXT NOT NULL,
    payload_json   TEXT NOT NULL DEFAULT '{}',
    started_at     INTEGER NOT NULL,
    ends_at        INTEGER,
    updated_at     INTEGER NOT NULL,
    FOREIGN KEY (resolution_key) REFERENCES gd_resolution_definitions(resolution_key)
);

CREATE INDEX IF NOT EXISTS idx_gd_resolution_state_key ON gd_resolution_state(resolution_key);

INSERT OR IGNORE INTO gd_resolution_definitions (
    resolution_key, label_key, description_key, category,
    mechanics_json, tradeoffs_json, duration_days, sort_order
) VALUES
(
    'ban_directive',
    'gdp_res_ban_directive_title',
    'gdp_res_ban_directive_desc',
    'directive_control',
    '{"flags":{"ban_directive_cycles":1}}',
    '{}',
    30,
    10
),
(
    'boost_directive',
    'gdp_res_boost_directive_title',
    'gdp_res_boost_directive_desc',
    'directive_control',
    '{"flags":{"directive_boost_mult":1.20}}',
    '{}',
    30,
    20
),
(
    'emergency_session',
    'gdp_res_emergency_session_title',
    'gdp_res_emergency_session_desc',
    'emergency',
    '{"flags":{"trigger_emergency_session":1}}',
    '{}',
    7,
    30
),
(
    'gate_control',
    'gdp_res_gate_control_title',
    'gdp_res_gate_control_desc',
    'territory',
    '{"flags":{"gate_control_active":1},"effect_resolver":{"research_time_speed":1.05},"alliance_mechanics":{"flags":{"expedition_loot_mult":1.05}}}',
    '{}',
    30,
    40
),
(
    'bloc_sanction',
    'gdp_res_bloc_sanction_title',
    'gdp_res_bloc_sanction_desc',
    'sanction',
    '{"flags":{"bloc_vote_weight_mult":0.85,"trader_daily_limit_mult":0.90}}',
    '{}',
    30,
    50
);
