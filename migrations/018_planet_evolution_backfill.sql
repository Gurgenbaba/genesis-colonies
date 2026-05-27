-- Planet Evolution — backfill homeworld DNA for existing planets

-- Homeworlds without DNA get seeded on next bootstrap via Python;
-- this migration ensures evolution tick column defaults are sane.
UPDATE planets SET last_evolution_tick = strftime('%s','now') WHERE last_evolution_tick IS NULL OR last_evolution_tick = 0;
