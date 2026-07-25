-- EPIC-21 / GC-P11: pirate_war emergency definition for Galactic Diplomacy

INSERT OR IGNORE INTO gd_emergency_definitions (
    emergency_key, label_key, description_key, category,
    mechanics_json, tradeoffs_json, duration_days, sort_order
) VALUES (
    'pirate_war',
    'gdp_emergency_pirate_war_title',
    'gdp_emergency_pirate_war_desc',
    'war',
    '{"effect_resolver":{"weapon_bonus":0.15,"shield_bonus":0.10,"defense_time_speed":1.20,"shipyard_time_speed":1.15},"flags":{"fleet_attack_bonus":0.08,"pirate_pressure":1}}',
    '{"effect_resolver":{"metal_prod_factor":0.92,"crystal_prod_factor":0.92,"fleet_speed_multiplier":0.95}}',
    21,
    25
);
