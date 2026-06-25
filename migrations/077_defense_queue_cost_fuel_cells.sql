-- GC-XXX: persist fuel_cells paid on defense queue rows for accurate cancel refund
ALTER TABLE defense_queue ADD COLUMN cost_fuel_cells REAL NOT NULL DEFAULT 0;
