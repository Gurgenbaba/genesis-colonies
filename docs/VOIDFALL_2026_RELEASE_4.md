# GC-VOIDFALL-004 — Rift Alignment

Extends Release 3 on DEV main and UNI1 u2/staging-runtime. Existing global milestone rewards, rare discovery odds, daily mission counting and the November 7 UTC event end are unchanged.

## One-time player choice

After **65 verified community daily-mission claim receipts** and **3 personally claimed daily missions** in the event, each account can select exactly one of:

- Forge Protocol — 2 existing 15-minute building boosters.
- Archive Protocol — 2 existing 15-minute research boosters.
- Pathfinder Protocol — 1 existing 24-hour expedition-loot +25% booster.

All three are already supported inventory items; no premium currency, Timekeeper, raw resource grant or new asset. Eligibility is account-wide regardless of colony count, not per-planet.

The one canonical receipt key `voidfall2026:alignment` stores the selected path in its reward JSON, and an existing UNIQUE(user_id, claim_key) constraint prevents two different paths. The /voidfall/claim route locks the account row before validation, and grant + receipt occur within the same transaction. Alignment claims do not increment community signals or roll rare discoveries; only successful daily mission claims do.

## UI and operations

Three choice cards join the existing Convergence area on /login-rewards, with server-derived totals, personal requirements, chosen/locked states and eight translations. Native CSRF-protected POST forms remain a no-JS fallback. Enhanced claim navigation calls `GC.navigateTo` (PJAX) when available, instead of a normal browser reload.

No new migration, table, recurring poll, background worker or image request. The event's pause and expiry gates apply to alignment exactly as to other claims. No automatic retroactive reward grants.

Release gate: targeted VOIDFALL tests (including required thresholds, cross-option exclusion, discovery exclusion, failed-grant no-receipt, UI/CSRF); full smoke, i18n, PG and browser sentinel checks on both PRs; then DEV deploy and health validation before UNI1; prelaunch reset must remain skipped.
