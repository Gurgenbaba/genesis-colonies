-- 029_orbital_shipyard_ships.sql
-- Orbital Shipyard building column + legacy ship key migration on planet_ships.

ALTER TABLE planet_buildings ADD COLUMN orbital_shipyard INTEGER DEFAULT 0 CHECK(orbital_shipyard >= 0);

UPDATE planet_buildings
SET orbital_shipyard = COALESCE(shipyard, 0)
WHERE COALESCE(orbital_shipyard, 0) < COALESCE(shipyard, 0);

-- Merge legacy ship stacks into canonical keys (planet_ships).
UPDATE planet_ships SET ship_key = 'mule_courier' WHERE ship_key = 'small_cargo';
UPDATE planet_ships SET ship_key = 'atlas_hauler' WHERE ship_key = 'large_cargo';
UPDATE planet_ships SET ship_key = 'falcon_interceptor' WHERE ship_key = 'light_fighter';
UPDATE planet_ships SET ship_key = 'ironclad_frigate' WHERE ship_key = 'heavy_fighter';
UPDATE planet_ships SET ship_key = 'veil_probe' WHERE ship_key = 'spy_probe';
UPDATE planet_ships SET ship_key = 'harvest_reclaimer' WHERE ship_key = 'recycler';
UPDATE planet_ships SET ship_key = 'solar_skiff' WHERE ship_key = 'expedition_vessel';

-- Collapse duplicate rows after rename (same planet_id + ship_key).
DELETE FROM planet_ships
WHERE id NOT IN (
    SELECT MIN(id)
    FROM planet_ships
    GROUP BY planet_id, ship_key
);
