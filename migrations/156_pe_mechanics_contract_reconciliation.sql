-- GC-REQUIRES-TABLES: pe_research_definitions, pe_policy_definitions, pe_discovery_definitions, pe_ascension_definitions
-- GC-PE-MECH-01: remove silently inert/deferred PE mechanics from the active
-- definition state. Historical seed 017 remains untouched; future features may
-- reintroduce deferred keys only together with a real runtime consumer.
-- Historical snapshots without the PE definition module are intentionally a no-op.

UPDATE pe_research_definitions
SET mechanics_json = '{}'
WHERE tech_key = 'industry_t4_mass_foundry';

UPDATE pe_research_definitions
SET mechanics_json = '{"enable_policy":"mandatory_overtime"}'
WHERE tech_key = 'industry_t5_overdrive';

UPDATE pe_policy_definitions
SET mechanics_json = '{}'
WHERE policy_key IN ('black_market_tolerated', 'martial_law', 'closed_borders');

UPDATE pe_discovery_definitions
SET mechanics_json = '{"unlock_chain":"living_crystal"}'
WHERE discovery_key = 'living_crystal_network';

UPDATE pe_discovery_definitions
SET mechanics_json = '{}'
WHERE discovery_key = 'quantum_rift';

UPDATE pe_discovery_definitions
SET mechanics_json = '{"auto_research_weekly":1}'
WHERE discovery_key = 'ancient_ai';

UPDATE pe_ascension_definitions
SET permanent_mechanics_json = '{"export_slots":2,"chain_output_mult":1.4}'
WHERE ascension_key = 'industrial_ascension';

-- discovery_roll_mult is intentionally retained: discoveries.py already has
-- the authoritative runtime consumer; mechanics.py now compiles this flag.
UPDATE pe_ascension_definitions
SET permanent_mechanics_json = '{"experimental_slot":2,"discovery_roll_mult":2.0}'
WHERE ascension_key = 'quantum_ascension';

UPDATE pe_ascension_definitions
SET permanent_mechanics_json = '{"auto_conversion":2}'
WHERE ascension_key = 'machine_ascension';

UPDATE pe_ascension_definitions
SET permanent_mechanics_json = '{}'
WHERE ascension_key = 'ancient_ascension';
