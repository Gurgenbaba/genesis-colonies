-- GC-LIVEOPS: preserve the newest asteroid at any duplicate active coordinates.
-- The older conflicting rows are marked expired; current fleet movements and
-- active asteroid resources remain intact.
UPDATE asteroid_fields SET status = 'expired'
WHERE status = 'active'
  AND id NOT IN (
      SELECT MAX(id) FROM asteroid_fields
      WHERE status = 'active'
      GROUP BY galaxy, system, position
  );

-- Prevent any two active asteroids (including standard and mega) sharing a slot.
CREATE UNIQUE INDEX IF NOT EXISTS idx_asteroid_fields_one_active_slot
ON asteroid_fields (galaxy, system, position)
WHERE status = 'active';

-- Activate built-in gameplay events on both universes, without shop promotions
-- or passive inactive-farming bonuses. Leave custom/admin-owned rules untouched.
UPDATE server_event_schedules SET enabled = 1
WHERE enabled = 0 AND created_by IS NULL
  AND (
      (id = 1 AND name = 'Weekend Prod / Expo' AND preset_id = 'weekend_prod_expo')
   OR (id = 3 AND name = 'Friday Asteroid Storm' AND preset_id = 'asteroid_storm_48h')
   OR (id = 4 AND name = 'Saturday Boss Hunt' AND preset_id = 'boss_hunt_24h')
  );
