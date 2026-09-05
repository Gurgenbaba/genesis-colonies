-- GC-PG-HIGHSPEED-001E: keep debris TTL cleanup off the maintenance hot path.
--
-- fleet_worker physically expires debris with:
--   DELETE FROM debris_fields WHERE updated_at <= ?
-- The original debris schema only indexed (galaxy, system, position), so PostgreSQL
-- had no index matching the maintenance predicate. Production logs showed the debris
-- stage occasionally holding its write transaction for >1s even when gameplay HTTP
-- was active. This additive index preserves all debris semantics while shortening the
-- lookup/lock window for TTL cleanup.
CREATE INDEX IF NOT EXISTS idx_debris_fields_updated_at
    ON debris_fields(updated_at);
