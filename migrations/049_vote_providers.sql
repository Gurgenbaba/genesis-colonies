-- 049_vote_providers.sql
-- GC-552: Multi-provider vote configuration (TopG, GameToor, extensible).

CREATE TABLE IF NOT EXISTS vote_providers (
    provider_key TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    vote_url_template TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    cooldown_sec INTEGER NOT NULL DEFAULT 43200,
    reward_key TEXT NOT NULL DEFAULT 'vote_container',
    reward_payload_json TEXT NOT NULL DEFAULT '{"box_key":"generic_supply_container","amount":1}',
    postback_enabled INTEGER NOT NULL DEFAULT 0 CHECK(postback_enabled IN (0, 1)),
    postback_config_json TEXT NOT NULL DEFAULT '{}',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

INSERT OR IGNORE INTO vote_providers (
    provider_key, display_name, vote_url_template, enabled, cooldown_sec,
    reward_key, reward_payload_json, postback_enabled, postback_config_json,
    sort_order, created_at
) VALUES
(
    'topg',
    'TopG',
    'https://topg.org/ogame-private-servers/server-683112-{user_id}#vote',
    1,
    43200,
    'vote_container',
    '{"box_key":"generic_supply_container","amount":1}',
    1,
    '{"remote_host":"monitor.topg.org","user_id_params":["p_resp"],"ip_params":["ip"],"require_numeric_user_id":true}',
    10,
    CAST(strftime('%s', 'now') AS INTEGER)
),
(
    'gametoor',
    'GameToor',
    'http://gametoor.com/in/327/',
    1,
    43200,
    'vote_container',
    '{"box_key":"generic_supply_container","amount":1}',
    1,
    '{"user_id_params":["userid","user_id","p_resp"],"ip_params":["userip","ip"],"require_numeric_user_id":true,"voted_param":"voted","require_voted_flag":true}',
    20,
    CAST(strftime('%s', 'now') AS INTEGER)
);
