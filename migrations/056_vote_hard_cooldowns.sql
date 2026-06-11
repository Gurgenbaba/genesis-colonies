-- 056_vote_hard_cooldowns.sql
-- GC-557A: Align GameToor and Arena-Top100 to 12h hard cooldowns.

UPDATE vote_providers
SET cooldown_sec = 43200
WHERE provider_key IN ('gametoor', 'arena_top100');
