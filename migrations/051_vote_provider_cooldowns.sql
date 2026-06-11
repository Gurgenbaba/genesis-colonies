-- 051_vote_provider_cooldowns.sql
-- GC-551C: TopG 6h cooldown, GameToor correct link, no postback.

UPDATE vote_providers
SET cooldown_sec = 21600,
    vote_url_template = 'https://topg.org/ogame-private-servers/server-683112-{user_id}#vote',
    postback_enabled = 1,
    postback_config_json = '{"user_id_params":["p_resp"],"ip_params":["ip"],"require_numeric_user_id":true,"remote_host":"monitor.topg.org","strict_ip_check":false}'
WHERE provider_key = 'topg';

UPDATE vote_providers
SET cooldown_sec = 86400,
    vote_url_template = 'http://gametoor.com/in/3277',
    postback_enabled = 0,
    postback_config_json = '{}'
WHERE provider_key = 'gametoor';
