-- 055_vote_gametoor_ivn.sql
-- GC-556: GameToor IVN vote provider.

UPDATE vote_providers
SET display_name = 'GameToor',
    vote_url_template = 'http://gametoor.com/in/3277/{user_id}',
    cooldown_sec = 86400,
    postback_enabled = 1,
    postback_config_json = '{}'
WHERE provider_key = 'gametoor';
