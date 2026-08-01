-- 126_imperial_directives_pve_pool.sql
-- Pause PvP player-attack directives; rebalance weights toward PvE / variety.

-- Disabled from roll pool (weight 0) — low active PvP + newbie protection
UPDATE directive_definitions SET weight = 0
WHERE key IN ('win_battles', 'destroy_enemy_ships', 'destroy_enemy_defense');

-- Boost PvE military
UPDATE directive_definitions SET weight = 14 WHERE key = 'defeat_pirates';
UPDATE directive_definitions SET weight = 12 WHERE key = 'deal_world_boss_damage';
UPDATE directive_definitions SET weight = 14 WHERE key = 'build_defense';
UPDATE directive_definitions SET weight = 12 WHERE key = 'build_combat_ships';

-- Lower sticky economy produce / building weights
UPDATE directive_definitions SET weight = 8
WHERE key IN ('produce_metal', 'produce_crystal', 'produce_fuel_cells');
UPDATE directive_definitions SET weight = 10 WHERE key = 'upgrade_buildings';

-- Boost fleet / science variety anchors
UPDATE directive_definitions SET weight = 16
WHERE key IN ('launch_expeditions', 'complete_expeditions');
UPDATE directive_definitions SET weight = 14 WHERE key = 'complete_research';
