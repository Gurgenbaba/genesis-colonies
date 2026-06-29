-- GC-972A: industry_t4_mass_foundry — OR-requirement (one Industry T3 path suffices)

UPDATE pe_research_definitions
SET requirements_json = '{"planet_research_any":["industry_t3_orbital_refinery","industry_t3_mantle_tap"]}'
WHERE tech_key = 'industry_t4_mass_foundry';
