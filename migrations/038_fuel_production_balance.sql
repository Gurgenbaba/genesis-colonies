-- 038_fuel_production_balance.sql
-- Lower Brennzellen base rate (speedgame x400: ~35% of Crytite at equal mine levels).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('fuel_production_per_hour', '4');
