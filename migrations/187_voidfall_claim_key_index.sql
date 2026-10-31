-- GC-VOIDFALL-003 — indexed reads for universe-wide daily mission receipts.
-- Existing Release 2 claims and inventories remain unchanged.
-- The ledger is the single source for completed, server-verified event signals.
CREATE INDEX IF NOT EXISTS idx_voidfall_reward_claim_key
    ON voidfall_reward_claims(claim_key);
