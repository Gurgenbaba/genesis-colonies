-- 170_troop_queue_exact_cost_snapshots.sql
-- GC-REQUIRES-TABLES: troop_queue
-- P1-B: troop training refunds must use the exact paid historical cost.
-- Canonical snapshot = decimal TEXT, matching build/research/shipyard/defense.

ALTER TABLE troop_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE troop_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0';

UPDATE troop_queue
SET cost_metal_exact = CAST(cost_metal AS TEXT),
    cost_crystal_exact = CAST(cost_crystal AS TEXT)
WHERE cost_metal_exact = '0'
  AND cost_crystal_exact = '0';
