-- 037_speedgame_exchange_defaults.sql
-- Speedgame Trader Hub balance (symmetric m<->c, fast fuel, 2B daily cap).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('exchange_rate_metal_to_crystal', '0.85'),
('exchange_rate_crystal_to_metal', '0.85'),
('exchange_daily_limit', '2000000000'),
('fuel_exchange_metal_per_unit', '20'),
('fuel_exchange_crystal_per_unit', '14');
