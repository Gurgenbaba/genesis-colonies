-- GC-WB-RAID-001: World Boss raid-phase balance.
--
-- Why this is NOT another max_hp multiplier:
-- World Boss damage is mapped as a fraction of max_hp in game/world_boss.py.
-- Raising only max_hp therefore changes the displayed number, but barely changes
-- the number of attacks required. The actual difficulty lever is the defender
-- prestige score used by compute_instant_hp_damage().
--
-- The old catalog also allowed most bosses to inherit/scale their current stacks
-- through phases. _resolve_phase_stacks() scales chosen stacks by remaining HP,
-- which made bosses progressively easier unless a phase supplied an explicit
-- stack override. This migration gives every raid phase an explicit encounter
-- stack and compensates for the remaining-HP scaling. Result: the effective
-- resistance stays roughly stable (or rises slightly) instead of collapsing.
--
-- The values are deliberately a first raid pass (~7.5x the original catalog
-- strength) rather than an unbounded HP inflation. Damage rankings, rewards,
-- cooldowns, shared HP, catch/tame and the existing combat-stat owner remain
-- untouched.

UPDATE world_boss_definitions
SET
    fleet_stacks_json = '{"falcon_interceptor":6000,"ironclad_frigate":1500,"eclipse_runner":300}',
    phases_json = '[{"hp_ratio":1.0,"stacks":{"falcon_interceptor":6000,"ironclad_frigate":1500,"eclipse_runner":300}},{"hp_ratio":0.55,"stacks":{"falcon_interceptor":11000,"ironclad_frigate":2750,"eclipse_runner":560}},{"hp_ratio":0.25,"stacks":{"falcon_interceptor":25000,"ironclad_frigate":6250,"eclipse_runner":1300}}]'
WHERE boss_key = 'ancient_leviathan';

UPDATE world_boss_definitions
SET
    fleet_stacks_json = '{"falcon_interceptor":9000,"ironclad_frigate":3000,"eclipse_runner":600}',
    phases_json = '[{"hp_ratio":1.0,"stacks":{"falcon_interceptor":9000,"ironclad_frigate":3000,"eclipse_runner":600}},{"hp_ratio":0.45,"stacks":{"falcon_interceptor":20500,"ironclad_frigate":6800,"eclipse_runner":1360}},{"hp_ratio":0.18,"stacks":{"falcon_interceptor":52000,"ironclad_frigate":17400,"eclipse_runner":3500}}]'
WHERE boss_key = 'void_titan';

UPDATE world_boss_definitions
SET
    fleet_stacks_json = '{"falcon_interceptor":4500,"ironclad_frigate":2250,"atlas_hauler":750,"eclipse_runner":375}',
    phases_json = '[{"hp_ratio":1.0,"stacks":{"falcon_interceptor":4500,"ironclad_frigate":2250,"atlas_hauler":750,"eclipse_runner":375}},{"hp_ratio":0.60,"stacks":{"falcon_interceptor":7800,"ironclad_frigate":3900,"atlas_hauler":1300,"eclipse_runner":650}},{"hp_ratio":0.30,"stacks":{"falcon_interceptor":16000,"ironclad_frigate":8000,"atlas_hauler":2650,"eclipse_runner":1350}}]'
WHERE boss_key = 'planet_eater';

UPDATE world_boss_definitions
SET
    fleet_stacks_json = '{"veil_probe":1500,"falcon_interceptor":6750,"ironclad_frigate":1125,"eclipse_runner":900}',
    phases_json = '[{"hp_ratio":1.0,"stacks":{"veil_probe":1500,"falcon_interceptor":6750,"ironclad_frigate":1125,"eclipse_runner":900}},{"hp_ratio":0.50,"stacks":{"veil_probe":3000,"falcon_interceptor":14000,"ironclad_frigate":2400,"eclipse_runner":1900}},{"hp_ratio":0.20,"stacks":{"veil_probe":7800,"falcon_interceptor":35500,"ironclad_frigate":6000,"eclipse_runner":4800}}]'
WHERE boss_key = 'rogue_ai_nexus';

-- Active encounters adopt the new phase-1 presentation immediately. The next
-- attack resolves the correct phase override from the updated definition based
-- on current_hp/max_hp, so mid-fight events transition without an HP reset.
UPDATE world_boss_events
SET fleet_stacks_json = CASE boss_key
    WHEN 'ancient_leviathan' THEN '{"falcon_interceptor":6000,"ironclad_frigate":1500,"eclipse_runner":300}'
    WHEN 'void_titan' THEN '{"falcon_interceptor":9000,"ironclad_frigate":3000,"eclipse_runner":600}'
    WHEN 'planet_eater' THEN '{"falcon_interceptor":4500,"ironclad_frigate":2250,"atlas_hauler":750,"eclipse_runner":375}'
    WHEN 'rogue_ai_nexus' THEN '{"veil_probe":1500,"falcon_interceptor":6750,"ironclad_frigate":1125,"eclipse_runner":900}'
    ELSE fleet_stacks_json
END,
updated_at = CAST(strftime('%s','now') AS REAL)
WHERE status = 'active'
  AND boss_key IN ('ancient_leviathan','void_titan','planet_eater','rogue_ai_nexus');
