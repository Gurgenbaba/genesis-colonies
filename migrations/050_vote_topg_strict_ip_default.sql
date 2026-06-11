-- 050_vote_topg_strict_ip_default.sql
-- GC-551B: TopG postback config — IP check controlled via TOPG_STRICT_IP_CHECK env (default off).

UPDATE vote_providers
SET postback_config_json = '{"user_id_params":["p_resp"],"ip_params":["ip"],"require_numeric_user_id":true,"remote_host":"monitor.topg.org","strict_ip_check":false}'
WHERE provider_key = 'topg'
  AND postback_config_json LIKE '%monitor.topg.org%';
