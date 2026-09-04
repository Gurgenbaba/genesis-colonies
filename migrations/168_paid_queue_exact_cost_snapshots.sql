-- 168_paid_queue_exact_cost_snapshots.sql
-- P0-C: Research, Shipyard and Defense paid costs must survive values above
-- signed BIGINT and must never depend on later cost recomputation.
-- Canonical snapshot = decimal TEXT, mirroring build_queue migration 163.
-- Legacy numeric columns stay for rolling-deploy compatibility; new writers
-- store 0 there when an integer cost exceeds signed i64.

ALTER TABLE research_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE research_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0';

UPDATE research_queue
SET cost_metal_exact = CAST(cost_metal AS TEXT),
    cost_crystal_exact = CAST(cost_crystal AS TEXT)
WHERE cost_metal_exact = '0' AND cost_crystal_exact = '0';

ALTER TABLE shipyard_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE shipyard_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE shipyard_queue ADD COLUMN cost_fuel_cells_exact TEXT NOT NULL DEFAULT '0';

UPDATE shipyard_queue
SET cost_metal_exact = CAST(cost_metal AS TEXT),
    cost_crystal_exact = CAST(cost_crystal AS TEXT),
    cost_fuel_cells_exact = CAST(cost_fuel_cells AS TEXT)
WHERE cost_metal_exact = '0'
  AND cost_crystal_exact = '0'
  AND cost_fuel_cells_exact = '0';

ALTER TABLE defense_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE defense_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE defense_queue ADD COLUMN cost_fuel_cells_exact TEXT NOT NULL DEFAULT '0';

UPDATE defense_queue
SET cost_metal_exact = CAST(cost_metal AS TEXT),
    cost_crystal_exact = CAST(cost_crystal AS TEXT),
    cost_fuel_cells_exact = CAST(cost_fuel_cells AS TEXT)
WHERE cost_metal_exact = '0'
  AND cost_crystal_exact = '0'
  AND cost_fuel_cells_exact = '0';
