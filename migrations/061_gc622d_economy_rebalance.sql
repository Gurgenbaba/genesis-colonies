-- 061_gc622d_economy_rebalance.sql
-- GC-622D: Brennzellen base production (growth nerf is in EffectResolver FUEL_CELL_GROWTH).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('fuel_production_per_hour', '2.0');
