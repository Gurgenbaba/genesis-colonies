-- 096_score_neutral_exchange.sql
-- GC-SCORE-F: align Trader Hub rates with canonical resource_score (3:2:1).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('exchange_rate_metal_to_crystal', '1.5'),
('exchange_rate_crystal_to_metal', '1'),
('fuel_exchange_metal_per_unit', '3'),
('fuel_exchange_crystal_per_unit', '2');
