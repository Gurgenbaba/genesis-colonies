-- 184_uni1_admin_speed_profile.sql
-- UNI1 live balance: seed the requested admin-controlled universe speeds.
-- Runtime ownership is switched from the hard x1 profile to custom after deploy.
-- No player, planet, queue or fleet-movement rows are modified.

INSERT INTO game_settings (key, value) VALUES
('production_speed', '2'),
('build_speed', '3'),
('speed', '3'),
('research_speed', '5'),
('fleet_speed_war', '2'),
('fleet_speed_holding', '3'),
('fleet_speed_peaceful', '5')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
