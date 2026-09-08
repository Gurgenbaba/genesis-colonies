-- GC-MANDO-RELAY-002: per-planet cooldowns for shipless own-empire logistics.
--
-- Direction semantics:
--   collect    -> cooldown belongs to the source planet after a successful harvest.
--   distribute -> cooldown belongs to the target planet after a successful delivery.
--
-- The planet row remains the transactional lock owner. This table only persists
-- the next ready timestamp so concurrent requests re-check after row locks serialize.
CREATE TABLE IF NOT EXISTS empire_resource_relay_cooldowns (
    player_id BIGINT NOT NULL,
    planet_id BIGINT NOT NULL,
    direction TEXT NOT NULL,
    ready_at BIGINT NOT NULL DEFAULT 0,
    updated_at BIGINT NOT NULL DEFAULT 0,
    PRIMARY KEY (player_id, planet_id, direction)
);

CREATE INDEX IF NOT EXISTS idx_empire_resource_relay_ready
    ON empire_resource_relay_cooldowns(player_id, direction, ready_at);
