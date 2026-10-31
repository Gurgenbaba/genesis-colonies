# VOIDFALL 2026 — Release 1: Rift Opening

**Status:** deployable / 7-day LiveOps opening. This is the first slice, not the full VOIDFALL quest and rewards system.

## Player-facing effect

- **Event:** VOIDFALL: Rift Opening
- **Window (UTC):** 2026-10-31 00:00:00 → 2026-11-07 23:59:59
- **Expedition stay time:** ×0.85 (15% shorter stay; flight time unchanged)
- **Research speed:** ×1.10 (10% faster; actual time reduction ≈9.1%)
- **Visibility:** existing active-event rail, event summaries, Login Rewards event banner/calendar and `/api/game-state`.

This is a **per-universe event**: the same migration ships separately to DEV (`main`) and UNI1 (`u2/staging-runtime`). It does not transfer rewards or progress between universes.

## Balance and safety

Both modifiers use the canonical `game/server_events.py` hooks. Existing weekend effects multiply normally: weekend expedition stay ×0.75 combined with VOIDFALL ×0.85 yields ×0.6375 stay time while both events are active; VOIDFALL does **not** add production, shop discounts or passive-farm multipliers. Research ×1.10 applies to newly evaluated timing; existing queue times are not retroactively shortened.

Migration 186 is PostgreSQL-only (the two live universes use PostgreSQL), so local SQLite test databases do not inherit a time-limited live campaign. It is INSERT-only, guarded by event slug; rerunning it cannot re-enable an event an operator paused. No resets, grants, Timekeeper claims or new economy tables. Event automatically stops affecting gameplay at the end timestamp. No periodic task is needed.

## Verification (both environments)

1. Migration `186_voidfall_rift_opening.sql` recorded and no DB errors.
2. Event slug `voidfall-rift-opening-2026` enabled and active within the UTC window.
3. `/api/game-state` reports `server_events.expedition_hold_mult` and `research_time_speed` reflecting the active events.
4. Event rail and Login Rewards render “VOIDFALL: Rift Opening” and the two localized modifier summaries.
5. Railway deployment SUCCESS, `/healthz` 200, worker healthy.
6. After 2026-11-07 23:59:59 UTC the event no longer applies.

## Deferred (not in Release 1)

Daily VOIDFALL tasks, Event Containers, a one-time comeback gift, exclusive discoveries, and community milestones require separate idempotent reward logic, tests and balancing. Do not advertise these as available until shipped.
