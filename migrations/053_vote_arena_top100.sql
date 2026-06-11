-- 053_vote_arena_top100.sql
-- GC-554: Arena-Top100 external vote provider (no postback yet).

INSERT OR IGNORE INTO vote_providers (
    provider_key, display_name, vote_url_template, enabled, cooldown_sec,
    reward_key, reward_payload_json, postback_enabled, postback_config_json,
    sort_order, created_at
) VALUES (
    'arena_top100',
    'Arena-Top100',
    'https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba',
    1,
    86400,
    'vote_container',
    '{"box_key":"generic_supply_container","amount":1}',
    0,
    '{}',
    40,
    CAST(strftime('%s', 'now') AS INTEGER)
);

UPDATE vote_providers
SET display_name = 'Arena-Top100',
    vote_url_template = 'https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba',
    cooldown_sec = 86400,
    postback_enabled = 0,
    sort_order = 40
WHERE provider_key = 'arena_top100';
