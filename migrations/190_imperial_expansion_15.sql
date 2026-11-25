-- Migrate the former 11-world default, but preserve other admin overrides.
-- No player or planet data touched.
UPDATE game_settings SET value = '15'
WHERE key = 'max_colonies_per_player' AND CAST(value AS INTEGER) = 11;
