-- 031_fuel_exchange_daily.sql
-- Per-planet daily limit tracking for Trader Hub fuel cell purchases.

ALTER TABLE planets ADD COLUMN fuel_exchange_daily_used REAL NOT NULL DEFAULT 0;
ALTER TABLE planets ADD COLUMN fuel_exchange_daily_reset_at REAL NOT NULL DEFAULT 0;
