-- GC-WB-RAID-002 — server-owned World Boss raid state.
-- Containment and Last Stand are derived from event timestamps; only shared/player gauges persist.

ALTER TABLE world_boss_events
    ADD COLUMN resonance_points INTEGER NOT NULL DEFAULT 0;

ALTER TABLE world_boss_events
    ADD COLUMN resonance_ends_at REAL;

ALTER TABLE world_boss_events
    ADD COLUMN resonance_initiator_player_id INTEGER;

ALTER TABLE world_boss_events
    ADD COLUMN finisher_player_id INTEGER;

ALTER TABLE world_boss_contributions
    ADD COLUMN target_lock INTEGER NOT NULL DEFAULT 0;
