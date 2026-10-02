-- 183_trader_hub_dev_parity.sql
-- Hotfix: UNI1 carried historical Trader Hub game_settings even though the
-- schema migration ledger was current. PostgreSQL must converge to the same
-- score-neutral values used by DEV/current runtime.
--
-- Player balances, exchange usage and exchange_log are intentionally untouched.
-- Legacy migration tests may start from a partial pre-settings schema, so keep
-- this backfill self-contained instead of assuming bootstrap already ran.

CREATE TABLE IF NOT EXISTS game_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO game_settings (key, value) VALUES
('exchange_enabled', '1'),
('exchange_rate_metal_to_crystal', '1.5'),
('exchange_rate_crystal_to_metal', '1'),
('exchange_daily_limit', '50000000000'),
('exchange_daily_limit_pct', '80'),
('exchange_daily_limit_min', '25000000'),
('exchange_daily_limit_max', '50000000000'),
('exchange_min_amount', '100'),
('fuel_exchange_enabled', '1'),
('fuel_exchange_metal_per_unit', '3'),
('fuel_exchange_crystal_per_unit', '2'),
('fuel_exchange_min_units', '10')
ON CONFLICT(key) DO UPDATE SET value = excluded.value;
