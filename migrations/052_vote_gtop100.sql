-- 052_vote_gtop100.sql
-- GC-553: GTop100 pingback vote provider.

INSERT OR IGNORE INTO vote_providers (
    provider_key, display_name, vote_url_template, enabled, cooldown_sec,
    reward_key, reward_payload_json, postback_enabled, postback_config_json,
    sort_order, created_at
) VALUES (
    'gtop100',
    'GTop100',
    'https://gtop100.com/Ogame/server-106142?vote=1&pingUsername={user_id}',
    1,
    43200,
    'vote_container',
    '{"box_key":"generic_supply_container","amount":1}',
    1,
    '{}',
    15,
    CAST(strftime('%s', 'now') AS INTEGER)
);

UPDATE vote_providers
SET display_name = 'GTop100',
    vote_url_template = 'https://gtop100.com/Ogame/server-106142?vote=1&pingUsername={user_id}',
    cooldown_sec = 43200,
    postback_enabled = 1,
    sort_order = 15
WHERE provider_key = 'gtop100';

UPDATE vote_providers
SET sort_order = 30
WHERE provider_key = 'gametoor';
