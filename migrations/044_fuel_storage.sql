-- 044_fuel_storage.sql
-- GC-535: Dedicated fuel cell storage building (planet-scoped, like metal/crystal storage).

ALTER TABLE planet_buildings ADD COLUMN fuel_storage INTEGER DEFAULT 0 CHECK(fuel_storage >= 0);

-- Existing colonies with a fuel cell plant receive a starter depot (level 1).
UPDATE planet_buildings
SET fuel_storage = 1
WHERE fuel_cell_plant >= 1
  AND COALESCE(fuel_storage, 0) = 0;
