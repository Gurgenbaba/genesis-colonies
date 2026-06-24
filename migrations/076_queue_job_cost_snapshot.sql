-- GC-831: persist paid costs on build/research queue rows for accurate cancel refunds.

ALTER TABLE build_queue ADD COLUMN cost_metal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE build_queue ADD COLUMN cost_crystal INTEGER NOT NULL DEFAULT 0;

ALTER TABLE research_queue ADD COLUMN cost_metal INTEGER NOT NULL DEFAULT 0;
ALTER TABLE research_queue ADD COLUMN cost_crystal INTEGER NOT NULL DEFAULT 0;
