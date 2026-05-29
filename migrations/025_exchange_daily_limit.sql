-- 025_exchange_daily_limit.sql
-- Raise instant exchange daily cap (existing installs that already ran 024).

INSERT OR REPLACE INTO game_settings (key, value) VALUES
('exchange_daily_limit', '500000000');
