-- 057_exchange_trader_limit_balance.sql
-- GC-558 follow-up: 80% empire production, 50B safety cap (live had 2B from 037).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('exchange_daily_limit', '50000000000'),
('exchange_daily_limit_pct', '80'),
('exchange_daily_limit_min', '25000000'),
('exchange_daily_limit_max', '50000000000');
