# GC-FLEET-PG-ABORT-003 — Action transaction domain isolation

Follow-up hardening for the PostgreSQL SAVEPOINT ownership repair.

## Invariant

A caller-owned `source="action"` transaction settles only the gameplay/account queue domains the mutation depends on. Fleet movement completion and planet relocation stay on their dedicated owners and are not pulled into research/build/evolution/ascension transactions by default.

`finish_due_work()` now owns this policy centrally: `include_fleet` and `include_relocations` are tri-state. `None` resolves to `False` for an already-open caller-owned action transaction and to the historical `True` everywhere else. Explicit `True` remains available for deliberate maintenance coupling.

This removes the need to scatter `include_fleet=False` / `include_relocations=False` across every present and future action call site and keeps the production fix aligned with the queue-domain refactor.
