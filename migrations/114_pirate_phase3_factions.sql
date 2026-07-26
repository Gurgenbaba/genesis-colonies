-- EPIC-21 Phase 3: ash_raiders + salt_cartel living AI factions.

INSERT OR IGNORE INTO pirate_faction_defs (
    faction_key, name_key, description_key, commander_key,
    aggression_weight, loot_tier, defense_tier,
    fleet_stacks_json, personality_json, sort_order, active
) VALUES
(
    'ash_raiders',
    'pirate_faction_ash_raiders',
    'pirate_faction_ash_raiders_desc',
    'pirate_commander_ash',
    90, 'high', 'medium',
    '{"falcon_interceptor":50,"ironclad_frigate":28,"eclipse_runner":12}',
    '{"attack_bias":0.9,"spy_bias":0.45,"turtle":0.2}',
    50, 1
),
(
    'salt_cartel',
    'pirate_faction_salt_cartel',
    'pirate_faction_salt_cartel_desc',
    'pirate_commander_salt',
    40, 'medium', 'high',
    '{"ironclad_frigate":20,"atlas_hauler":14,"falcon_interceptor":18}',
    '{"attack_bias":0.4,"spy_bias":0.35,"turtle":0.75}',
    60, 1
);
