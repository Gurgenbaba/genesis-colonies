-- LiveOps Event Scheduler — recurring rules that INSERT server_events windows.
-- Never mutates active events; materialize is INSERT-only + idempotent key.

CREATE TABLE IF NOT EXISTS server_event_schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    preset_id TEXT NOT NULL DEFAULT '',
    effects_json TEXT NOT NULL DEFAULT '[]',
    rrule_kind TEXT NOT NULL DEFAULT 'weekly'
        CHECK (rrule_kind IN ('weekly', 'daily', 'once')),
    weekdays_json TEXT NOT NULL DEFAULT '[]',
    local_start_hhmm TEXT NOT NULL DEFAULT '18:00',
    duration_sec INTEGER NOT NULL DEFAULT 0,
    tz_offset_minutes INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    last_materialized_key TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER
);

CREATE INDEX IF NOT EXISTS idx_server_event_schedules_enabled
    ON server_event_schedules (enabled, priority DESC);

-- Default LiveOps calendar templates (UTC+2). Seeded DISABLED so live deploys
-- do not auto-materialize weekend chaos until an admin enables rules.
-- duration_sec=0 → use preset duration resolver (e.g. until Sunday 20:00).
INSERT OR IGNORE INTO server_event_schedules (
    id, name, preset_id, effects_json, rrule_kind, weekdays_json,
    local_start_hhmm, duration_sec, tz_offset_minutes, priority, enabled,
    last_materialized_key, created_at, updated_at, created_by
) VALUES
(1, 'Weekend Prod / Expo', 'weekend_prod_expo', '[]', 'weekly', '[4]',
 '18:00', 0, 120, 100, 0, '', strftime('%s','now'), strftime('%s','now'), NULL),
(2, 'Sunday Shop Sale', 'shop_sale_20_48h', '[]', 'weekly', '[6]',
 '12:00', 86400, 120, 90, 0, '', strftime('%s','now'), strftime('%s','now'), NULL),
(3, 'Friday Asteroid Storm', 'asteroid_storm_48h', '[]', 'weekly', '[4]',
 '20:00', 172800, 120, 80, 0, '', strftime('%s','now'), strftime('%s','now'), NULL),
(4, 'Saturday Boss Hunt', 'boss_hunt_24h', '[]', 'weekly', '[5]',
 '16:00', 86400, 120, 80, 0, '', strftime('%s','now'), strftime('%s','now'), NULL),
(5, 'Inactive Farm Weekend', 'inactive_farm_weekend', '[]', 'weekly', '[4]',
 '18:00', 0, 120, 70, 0, '', strftime('%s','now'), strftime('%s','now'), NULL);
