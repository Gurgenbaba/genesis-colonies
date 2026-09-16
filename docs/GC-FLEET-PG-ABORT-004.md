# GC-FLEET-PG-ABORT-004 — Detached Fleet transaction owner

Follow-up to request-level PostgreSQL connection pinning. A call to `db()` from inside an HTTP request intentionally returns the request-pinned checkout, so a Fleet domain owner needs an explicit detached checkout.

`db_detached()` now provides that boundary. Online Fleet due-work and Admin Fleet force-advance use it. Admin force-advance no longer runs a generic player Fleet tick or an outer Admin request transaction: it advances exactly the selected movement phase through the existing per-movement short-TX owner.

This keeps the refactor invariant explicit: HTTP request transactions own HTTP mutations; Fleet movement state transitions own Fleet transactions.
