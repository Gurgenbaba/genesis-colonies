-- 080_imperial_directives.sql
-- GC-911A: Imperial Directives schema + definition seed (player High Command).

CREATE TABLE IF NOT EXISTS directive_definitions (
    key              TEXT PRIMARY KEY NOT NULL,
    category         TEXT NOT NULL,
    cadence          TEXT NOT NULL DEFAULT 'daily',
    objective_kind   TEXT NOT NULL DEFAULT 'count',
    base_target      INTEGER NOT NULL DEFAULT 1,
    scale_profile    TEXT NOT NULL DEFAULT 'count_light',
    weight           INTEGER NOT NULL DEFAULT 10,
    min_rarity       TEXT NOT NULL DEFAULT 'common',
    max_rarity       TEXT NOT NULL DEFAULT 'legendary',
    filters_json     TEXT NOT NULL DEFAULT '{}',
    title_key        TEXT NOT NULL,
    description_key  TEXT NOT NULL,
    sort_order       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS player_directives (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id        INTEGER NOT NULL,
    definition_key   TEXT NOT NULL,
    cadence          TEXT NOT NULL,
    rarity           TEXT NOT NULL,
    target_value     INTEGER NOT NULL,
    progress_value   INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'active',
    reward_json      TEXT NOT NULL DEFAULT '{}',
    period_key       TEXT NOT NULL,
    expires_at       INTEGER NOT NULL,
    completed_at     INTEGER,
    claimed_at       INTEGER,
    created_at       INTEGER NOT NULL,
    FOREIGN KEY(player_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(definition_key) REFERENCES directive_definitions(key)
);

CREATE INDEX IF NOT EXISTS idx_player_directives_player_period
    ON player_directives(player_id, cadence, period_key);

CREATE INDEX IF NOT EXISTS idx_player_directives_player_status
    ON player_directives(player_id, status);

CREATE TABLE IF NOT EXISTS directive_progress (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    player_directive_id  INTEGER NOT NULL,
    source_event_id      TEXT NOT NULL,
    delta                INTEGER NOT NULL DEFAULT 0,
    created_at           INTEGER NOT NULL,
    UNIQUE(player_directive_id, source_event_id),
    FOREIGN KEY(player_directive_id) REFERENCES player_directives(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_directive_progress_directive
    ON directive_progress(player_directive_id);

-- Definition seed (see game/directives/definitions.py)
INSERT OR IGNORE INTO directive_definitions (
    key, category, cadence, objective_kind, base_target, scale_profile,
    weight, min_rarity, max_rarity, filters_json, title_key, description_key, sort_order
) VALUES
('upgrade_buildings', 'economy', 'both', 'count', 3, 'count_light', 14, 'common', 'epic', '{}', 'id_def_upgrade_buildings_title', 'id_def_upgrade_buildings_desc', 10),
('produce_metal', 'economy', 'both', 'accumulate', 150000, 'produce', 16, 'common', 'legendary', '{"resource":"metal"}', 'id_def_produce_metal_title', 'id_def_produce_metal_desc', 20),
('produce_crystal', 'economy', 'both', 'accumulate', 120000, 'produce', 16, 'common', 'legendary', '{"resource":"crystal"}', 'id_def_produce_crystal_title', 'id_def_produce_crystal_desc', 30),
('produce_fuel_cells', 'economy', 'both', 'accumulate', 80000, 'produce', 14, 'common', 'legendary', '{"resource":"fuel_cells"}', 'id_def_produce_fuel_title', 'id_def_produce_fuel_desc', 40),
('spend_resources', 'economy', 'daily', 'accumulate', 50000, 'produce', 12, 'common', 'rare', '{}', 'id_def_spend_resources_title', 'id_def_spend_resources_desc', 50),
('upgrade_storages', 'economy', 'daily', 'count', 2, 'count_light', 10, 'common', 'rare', '{"building_types":["metal_storage","crystal_storage","fuel_storage"]}', 'id_def_upgrade_storages_title', 'id_def_upgrade_storages_desc', 60),
('upgrade_solar_plants', 'economy', 'daily', 'count', 2, 'count_light', 8, 'common', 'rare', '{"building_types":["solar_plant"]}', 'id_def_upgrade_solar_title', 'id_def_upgrade_solar_desc', 70),
('upgrade_fuel_plants', 'economy', 'daily', 'count', 2, 'count_light', 8, 'common', 'rare', '{"building_types":["fuel_cell_plant"]}', 'id_def_upgrade_fuel_plant_title', 'id_def_upgrade_fuel_plant_desc', 80),
('start_research', 'science', 'daily', 'count', 2, 'count_light', 12, 'common', 'rare', '{}', 'id_def_start_research_title', 'id_def_start_research_desc', 100),
('complete_research', 'science', 'both', 'count', 2, 'count_medium', 14, 'common', 'epic', '{}', 'id_def_complete_research_title', 'id_def_complete_research_desc', 110),
('upgrade_mining_tech', 'science', 'daily', 'count', 1, 'count_light', 8, 'common', 'rare', '{"research_keys":["mining_tech"]}', 'id_def_upgrade_mining_tech_title', 'id_def_upgrade_mining_tech_desc', 120),
('upgrade_energy_tech', 'science', 'daily', 'count', 1, 'count_light', 8, 'common', 'rare', '{"research_keys":["energy_tech"]}', 'id_def_upgrade_energy_tech_title', 'id_def_upgrade_energy_tech_desc', 130),
('upgrade_navigation_tech', 'science', 'daily', 'count', 1, 'count_light', 8, 'common', 'rare', '{"research_keys":["navigation_tech"]}', 'id_def_upgrade_navigation_tech_title', 'id_def_upgrade_navigation_tech_desc', 140),
('spend_research_resources', 'science', 'daily', 'accumulate', 40000, 'produce', 10, 'common', 'rare', '{}', 'id_def_spend_research_resources_title', 'id_def_spend_research_resources_desc', 150),
('launch_expeditions', 'fleet', 'daily', 'count', 3, 'count_medium', 12, 'common', 'epic', '{}', 'id_def_launch_expeditions_title', 'id_def_launch_expeditions_desc', 200),
('complete_expeditions', 'fleet', 'both', 'count', 3, 'count_medium', 14, 'common', 'legendary', '{}', 'id_def_complete_expeditions_title', 'id_def_complete_expeditions_desc', 210),
('send_fleet_missions', 'fleet', 'daily', 'count', 4, 'count_light', 12, 'common', 'rare', '{}', 'id_def_send_fleet_missions_title', 'id_def_send_fleet_missions_desc', 220),
('recycle_debris', 'fleet', 'daily', 'count', 2, 'count_light', 8, 'common', 'rare', '{}', 'id_def_recycle_debris_title', 'id_def_recycle_debris_desc', 230),
('build_ships', 'fleet', 'both', 'count', 5, 'count_medium', 14, 'common', 'epic', '{}', 'id_def_build_ships_title', 'id_def_build_ships_desc', 240),
('win_battles', 'military', 'both', 'count', 2, 'count_heavy', 12, 'rare', 'legendary', '{}', 'id_def_win_battles_title', 'id_def_win_battles_desc', 300),
('destroy_enemy_ships', 'military', 'both', 'count', 10, 'count_heavy', 10, 'rare', 'legendary', '{}', 'id_def_destroy_ships_title', 'id_def_destroy_ships_desc', 310),
('destroy_enemy_defense', 'military', 'daily', 'count', 5, 'count_medium', 8, 'common', 'epic', '{}', 'id_def_destroy_defense_title', 'id_def_destroy_defense_desc', 320),
('build_defense', 'military', 'both', 'count', 4, 'count_medium', 12, 'common', 'epic', '{}', 'id_def_build_defense_title', 'id_def_build_defense_desc', 330),
('build_combat_ships', 'military', 'daily', 'count', 3, 'count_medium', 10, 'common', 'epic', '{"ship_combat_only":true}', 'id_def_build_combat_ships_title', 'id_def_build_combat_ships_desc', 340),
('defeat_pirates', 'military', 'daily', 'count', 2, 'count_medium', 8, 'common', 'rare', '{"npc_tag":"pirate"}', 'id_def_defeat_pirates_title', 'id_def_defeat_pirates_desc', 350),
('trigger_expedition_events', 'exploration', 'daily', 'count', 2, 'count_light', 10, 'common', 'rare', '{}', 'id_def_trigger_expedition_events_title', 'id_def_trigger_expedition_events_desc', 400),
('find_rare_loot', 'exploration', 'daily', 'count', 1, 'count_light', 8, 'common', 'epic', '{"min_loot_rarity":"rare"}', 'id_def_find_rare_loot_title', 'id_def_find_rare_loot_desc', 410),
('recover_ancient_technology', 'exploration', 'weekly', 'count', 1, 'count_light', 6, 'rare', 'legendary', '{"event_type":"ancient_tech"}', 'id_def_recover_ancient_tech_title', 'id_def_recover_ancient_tech_desc', 420),
('salvage_ancient_ships', 'exploration', 'weekly', 'count', 1, 'count_light', 6, 'rare', 'legendary', '{"event_type":"ancient_ship"}', 'id_def_salvage_ancient_ships_title', 'id_def_salvage_ancient_ships_desc', 430);
