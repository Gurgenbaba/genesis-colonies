-- 151_stellar_forge_manufacturing_roles.sql
-- EPIC-30 / GC-3009: Manufacturing Trial — 3 categories chosen randomly per
-- campaign instead of the removed 60%-of-total cap (GC-3008).

ALTER TABLE planet_shipyard_ascension
    ADD COLUMN manufacturing_roles TEXT NOT NULL DEFAULT '[]';
