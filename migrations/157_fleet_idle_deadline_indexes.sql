-- GC-PERF-FLEET-IDLE-002
-- GC-REQUIRES-TABLES: fleet_movements
-- High-frequency player polls probe only whether a Fleet phase is due.
-- Keep those timestamp checks index-backed; global worker already had arrival/return
-- indexes, but holding_until had no equivalent deadline index.

CREATE INDEX IF NOT EXISTS idx_fleet_movements_player_arrival
    ON fleet_movements(player_id, status, arrival_at);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_player_holding
    ON fleet_movements(player_id, status, holding_until);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_player_return
    ON fleet_movements(player_id, status, return_at);

CREATE INDEX IF NOT EXISTS idx_fleet_movements_holding
    ON fleet_movements(status, holding_until);
