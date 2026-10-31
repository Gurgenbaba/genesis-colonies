# GC-VOIDFALL-006 — small-community 20/40/70 tuning

2026-10-31 balance change to live VOIDFALL Release 3 and Release 4. Each universe has its own independent shared signal total (DEV and UNI1 never mix). Approximately ten active players were reported, so the formerly required 65/150 signals were disproportionately high.

**New thresholds**: First Breach = 20 (unchanged); Rift Stabilization = 40 (formerly 65); Contain the Abyss = 70 (formerly 150). Rift Alignment unlocks at **40 global signals** (formerly 65), retaining the personal prerequisite of **3 verified daily mission claims**. All eight translated player-facing alignment hints are updated.

This modifies only server-side constant thresholds, corresponding translated hints and regression tests; it does not write an account receipt or migrate a database. Existing daily claim receipts and already granted community rewards retain their canonical identifiers and remain untouched. Lowered thresholds work immediately against the cumulative verified daily receipts from the existing event. No expiry, event pause, RNG, 5% discovery chance, reward amount, account-level cap, or UTC day cap changes.

Smoke / LiveOps / PostgreSQL / i18n / Sentinel must pass on both DEV and UNI1; deploy DEV first, then UNI1 with reset skipped.
