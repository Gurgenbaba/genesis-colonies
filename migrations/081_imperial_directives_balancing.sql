-- 081_imperial_directives_balancing.sql
-- GC-915: Lower base targets and tune scale profiles for realistic daily/weekly goals.

UPDATE directive_definitions SET base_target = 3, scale_profile = 'count_light'
WHERE key IN ('upgrade_buildings', 'upgrade_storages', 'upgrade_solar_plants', 'upgrade_fuel_plants');

UPDATE directive_definitions SET base_target = 3, scale_profile = 'count_medium'
WHERE key IN ('launch_expeditions', 'complete_expeditions');

UPDATE directive_definitions SET base_target = 10, scale_profile = 'count_light'
WHERE key = 'send_fleet_missions';

UPDATE directive_definitions SET base_target = 1, scale_profile = 'count_light'
WHERE key = 'start_research';

UPDATE directive_definitions SET base_target = 1, scale_profile = 'count_medium'
WHERE key = 'complete_research';

UPDATE directive_definitions SET base_target = 1, scale_profile = 'count_heavy'
WHERE key = 'win_battles';

UPDATE directive_definitions SET base_target = 5, scale_profile = 'ships'
WHERE key IN ('build_ships', 'build_combat_ships', 'build_defense');

UPDATE directive_definitions SET base_target = 3, scale_profile = 'ships'
WHERE key IN ('destroy_enemy_ships', 'destroy_enemy_defense');

UPDATE directive_definitions SET base_target = 5000, scale_profile = 'produce'
WHERE key IN ('produce_metal', 'produce_crystal', 'produce_fuel_cells');

UPDATE directive_definitions SET base_target = 3000, scale_profile = 'produce'
WHERE key IN ('spend_resources', 'spend_research_resources');

UPDATE directive_definitions SET base_target = 2, scale_profile = 'count_light'
WHERE key IN ('recycle_debris', 'defeat_pirates', 'trigger_expedition_events', 'find_rare_loot');
