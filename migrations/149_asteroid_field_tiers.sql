-- 149_asteroid_field_tiers.sql
-- GC-AST-MEGA: tiered asteroid fields. Adds a "mega" tier that supports
-- atomic partial/sequential multi-claim depletion (see try_claim_harvest in
-- game/asteroids.py) instead of the standard tier's first-arrival-wins-all.
-- Standard-tier fields and their existing claim path are unaffected.

ALTER TABLE asteroid_fields ADD COLUMN tier TEXT NOT NULL DEFAULT 'standard'
    CHECK(tier IN ('standard', 'mega'));

-- Per-claim ledger for mega-belt sequential depletion: audit trail, board UI
-- ("N fleets have already hit this field"), and a way to prove no lost
-- updates across concurrent claimers (sum(claims) == initial_pool - final_pool).
CREATE TABLE IF NOT EXISTS asteroid_field_claims (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    asteroid_id         INTEGER NOT NULL,
    player_id           INTEGER NOT NULL,
    claimed_at          REAL NOT NULL,
    metal               REAL NOT NULL DEFAULT 0,
    crystal             REAL NOT NULL DEFAULT 0,
    fuel_cells          REAL NOT NULL DEFAULT 0,
    FOREIGN KEY(asteroid_id) REFERENCES asteroid_fields(id) ON DELETE CASCADE,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_asteroid_field_claims_asteroid
    ON asteroid_field_claims(asteroid_id);

CREATE INDEX IF NOT EXISTS idx_asteroid_field_claims_player
    ON asteroid_field_claims(player_id);
