-- GC-REQUIRES-TABLES: pe_ascension_definitions
-- GC-ASC-L15-001: Planet Evolution Ascension unlock contract.
-- Existing universes were seeded with planet_level_min=25 in migration 017.
-- The live contract is now level 15; preserve every other path-specific gate.

UPDATE pe_ascension_definitions
SET requirements_json = '{"planet_level_min":15,"specialization_tier_min":3,"cost":{"metal":5000000,"crystal":3000000}}'
WHERE ascension_key = 'machine_ascension';

UPDATE pe_ascension_definitions
SET requirements_json = '{"planet_level_min":15,"specialization_tier_min":3,"discoveries_any":["quantum_rift","dark_core"]}'
WHERE ascension_key = 'quantum_ascension';

UPDATE pe_ascension_definitions
SET requirements_json = '{"planet_level_min":15,"specialization":"forge_world","specialization_tier_min":3}'
WHERE ascension_key = 'industrial_ascension';

UPDATE pe_ascension_definitions
SET requirements_json = '{"planet_level_min":15,"discoveries_any":["alien_vault","ancient_ai"],"traits_any":["ancient_ruins"]}'
WHERE ascension_key = 'ancient_ascension';
