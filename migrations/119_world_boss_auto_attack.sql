-- GC-WB-AUTO-004: server-owned World Boss auto-attack flag + ship snapshot
ALTER TABLE world_boss_contributions ADD COLUMN auto_attack_enabled INTEGER NOT NULL DEFAULT 0;
ALTER TABLE world_boss_contributions ADD COLUMN auto_attack_ships_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE world_boss_contributions ADD COLUMN auto_attack_planet_id INTEGER;
