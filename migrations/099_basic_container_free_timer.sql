-- 099_basic_container_free_timer.sql
-- Free standard-container timer: starts on first grant, not reset by stock opens.

ALTER TABLE players ADD COLUMN basic_container_timer_started_at REAL;
ALTER TABLE players ADD COLUMN basic_container_next_free_at REAL;

-- Backfill for players who already own or owned a standard container.
UPDATE players
SET
  basic_container_timer_started_at = (
    SELECT MIN(pii.created_at)
    FROM player_inventory_items pii
    WHERE pii.user_id = players.id AND pii.item_key = 'container_basic'
  ),
  basic_container_next_free_at = (
    SELECT MIN(pii.created_at) + 86400.0
    FROM player_inventory_items pii
    WHERE pii.user_id = players.id AND pii.item_key = 'container_basic'
  )
WHERE basic_container_timer_started_at IS NULL
  AND EXISTS (
    SELECT 1 FROM player_inventory_items pii
    WHERE pii.user_id = players.id AND pii.item_key = 'container_basic'
  );
