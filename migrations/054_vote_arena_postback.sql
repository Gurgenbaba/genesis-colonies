-- 054_vote_arena_postback.sql
-- GC-555: Arena-Top100 postback + Arena reset cooldown.

ALTER TABLE vote_rewards ADD COLUMN provider_next_vote_at INTEGER;

UPDATE vote_providers
SET display_name = 'Arena-Top100',
    vote_url_template = 'https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba&id={user_id}',
    postback_enabled = 1,
    postback_config_json = '{"user_id_params":["userid"],"ip_params":["userip"],"require_numeric_user_id":true,"voted_param":"voted","voted_value":"1"}'
WHERE provider_key = 'arena_top100';
