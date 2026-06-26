-- GC-OPS: universe-wide fleet mission lockdown (game_settings JSON blob).
INSERT OR IGNORE INTO game_settings (key, value)
VALUES ('fleet_mission_locks_json', '{}');
