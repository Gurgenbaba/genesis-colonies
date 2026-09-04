-- GC-FERRO-L388-001
-- GC-REQUIRES-TABLES: build_queue
-- Build upgrade costs exceed signed BIGINT from Ferronit Mine L388 onward.
-- Preserve the canonical paid snapshot losslessly while keeping legacy i64
-- columns for rolling-deploy compatibility (overflow rows store legacy 0).

ALTER TABLE build_queue ADD COLUMN cost_metal_exact TEXT NOT NULL DEFAULT '0';
ALTER TABLE build_queue ADD COLUMN cost_crystal_exact TEXT NOT NULL DEFAULT '0';

UPDATE build_queue
SET cost_metal_exact = CAST(cost_metal AS TEXT),
    cost_crystal_exact = CAST(cost_crystal AS TEXT)
WHERE cost_metal_exact = '0' AND cost_crystal_exact = '0';
