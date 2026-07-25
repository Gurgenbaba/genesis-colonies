-- GC-W11: World Boss HP catalog bump (5×) for readable bars; hit-count is still
-- governed by WAVE_HP_FRACTION / MAX_WAVE_HP_FRACTION in game/world_boss.py.
-- Active events keep remaining HP ratio.

UPDATE world_boss_definitions
SET max_hp = max_hp * 5
WHERE max_hp > 0;

UPDATE world_boss_events
SET
  current_hp = CAST(ROUND(current_hp * 5.0) AS INTEGER),
  max_hp = max_hp * 5
WHERE max_hp > 0;
