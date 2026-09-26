-- GC-SUPPORT-OFFICE-DELIVERY-001
-- Idempotency ledger for authenticated Gurgenbaba Office -> Genesis replies.

CREATE TABLE IF NOT EXISTS support_office_deliveries (
    delivery_id TEXT PRIMARY KEY,
    ticket_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_support_office_deliveries_ticket
    ON support_office_deliveries(ticket_id, created_at DESC);
