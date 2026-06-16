-- 060_gc622c_infinite_scaling_balance.sql
-- GC-622C: lower Brennzellen base production (growth nerf is in EffectResolver).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('fuel_production_per_hour', '3');
