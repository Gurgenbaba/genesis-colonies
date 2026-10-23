-- GC-VOTE-ARCA-001: ARCAVOTE provider. Runtime URL + HMAC secrets are env-only.
-- GC-REQUIRES-TABLES: vote_providers
-- Do not use the seed template as a public link; it is replaced by the
-- verified ARCAVOTE_GAME_URL in game/vote_rewards.py once fully configured.
INSERT INTO vote_providers (
    provider_key, display_name, vote_url_template, enabled, cooldown_sec,
    reward_key, reward_payload_json, postback_enabled, postback_config_json,
    sort_order, created_at
) VALUES (
    'arcavote',
    'ARCAVOTE',
    '',
    1,
    43200,
    'vote_container',
    '{"box_key":"generic_supply_container","amount":1}',
    1,
    '{}',
    5,
    CAST(strftime('%s', 'now') AS INTEGER)
)
ON CONFLICT (provider_key) DO NOTHING;
