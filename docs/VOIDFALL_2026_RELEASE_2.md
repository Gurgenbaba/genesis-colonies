# VOIDFALL — Release 2: Daily Ops & Welcome Drop

**Targets:** DEV main and UNI1 u2/staging-runtime. No reset or new images.

## Player content

Integrated into /login-rewards; CSS and JS persist across PJAX navigation.

- **Welcome supplies:** once per commander during the event, 1 rare container + 1 research 15-minute booster. Equal for existing and new accounts.
- **Rift exploration:** 2 completed expeditions today → 1 expedition-loot +25% 24-hour booster.
- **Fortify your colony:** 1 finished building today → 1 build 15-minute booster.
- **Operational readiness:** 3 completed actions (expedition, building, research, spy, recycle) → 1 event-special container.

Two expeditions and one finished building suffice for all objectives on **one planet**. Multi-planet empires cannot claim more. No premium requirement, Timekeeper, direct raw-resource grants or new currencies. Daily UTC reset at 00:00. Each reward capped once per account per UTC day.

## Source of truth / security

game/voidfall.py queries existing activity_xp_log and server_events. It never trusts clicks as progress.
Migration 186 creates a unique (user_id, claim_key) ledger with foreign-key cascade.
POST /voidfall/claim:
1. Login + CSRF required for HTML form and JSON.
2. Short DB write transaction with account row lock on PostgreSQL.
3. Validates event active and in UTC window, whitelisted key, completed progress and unique unclaimed key.
4. Canonical grant_inventory_item and receipt insert in the same transaction; failed/duplicate requests roll back.
5. Native HTML redirect fallback and enhanced JSON.
Only one whitelist key per call; no client-controlled quantities, timestamps or rewards. Text uses all eight supported languages.

## Release gate

- CI smoke, LiveOps (including tests/test_voidfall_ops.py), i18n, PG and browser sentinel green.
- DEV deployment SUCCESS + healthz 200 + workers; then UNI1.
- Confirm on live login rewards page three objectives, welcome claim, and UTC reset.
- No prelaunch reset, no existing player-state wipe.
- Event ends automatically after November 7 2026 at 23:59:59 UTC.

**Not in this slice:** Community milestones and exclusive story discoveries.
