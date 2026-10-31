# GC-VOIDFALL-003 — Convergence (Community Milestones + Rift Discoveries)

Release 3 extends Release 2, with NO new premium item sources, Timekeeper distribution, new resource economy, or game-state reconstruction. Scope: DEV main + UNI1 u2/staging-runtime. Each environment holds its own Postgres database and therefore its own **universe-wide** scoreboard.

## Global signal progression

Only successful, already server-validated Release 2 **daily mission claim receipts** count as community signals; not raw expedition launches, premium purchases or the welcome reward. Existing daily receipts from the start of VOIDFALL count retroactively. Mission receipts are unique per (player, mission, UTC day), max **3/account/day**, independent of colony count.

- 20 signals — First Breach: 1 rare container per qualifying account.
- 65 signals — Rift Stabilization: 1 event-special container per qualifying account.
- 150 signals — Contain the Abyss: 1 relic container per qualifying account.

**Eligibility:** Before claiming a globally unlocked milestone, the player must personally have claimed at least one daily VOIDFALL mission. Players who join later can qualify while the event remains active. A community claim NEVER adds an extra signal.

Reads use an indexed claim_key range in the existing voidfall_reward_claims ledger, restricted to the event's 2026-10-31..2026-11-07 days. New migration 187 only adds the required nonunique lookup index.

## Rare discovery system

After successfully claiming a daily mission, a server cryptographic RNG rolls **5%**. If successful it selects:
- 75% chance **Rift Echo:** 1 event-special container.
- 20% chance **Forgotten Rift Relic:** 1 relic container.
- 5% chance **Forbidden Void Artifact:** 1 void-artifact container.

Each account can receive at most **two** discoveries across the entire event. Claim attempts, retries, welcome rewards, community rewards and raw unclaimed actions never reroll. The discovery grant and receipt are written **inside the same account-locked database transaction** as the original daily mission. Any failure rolls both grants back. No pity reward has been promised.

## UX and release contract

- Community milestone progress, personal eligibility and discoverable history appear below VOIDFALL daily missions on /login-rewards.
- Claims use the existing CSRF-protected POST /voidfall/claim with native HTML fallback and PJAX-safe JS.
- Rarity discovery is shown after the successful claim navigation, and its reward remains in canonical Inventory.
- Eight localized interfaces: de/en/es/fr/pl/pt/ru/tr.
- No new raster assets or image network fetches, no recurring background polls, and no event-scoped worker.
- Existing VOIDFALL event remains operator-controlled (pause and end respected). Event ends 2026-11-07 23:59:59 UTC; unclaimed rewards expire with event.

## Acceptance gates

1. Targeted LiveOps tests: existing + community, including exact-once milestone, contribution fairness, discovery cap, tier distribution, rollback and expiry.
2. CI smoke + i18n + PG transaction/numeric + browser sentinel 100% pass on both base branches.
3. DEV merge and Railway SUCCESS first; migration 187 applied, healthz HTTP 200, worker sidecars active.
4. UNI1 merge and Railway SUCCESS only after DEV checks, with prelaunch-reset verified skipped.
5. No direct synthetic production claims: verify with read-only production logs and web responses. Do not promise a rare drop to an individual player.

## Analytics note

No shared cross-universe leaderboard: DEV and UNI1 are isolated. Scores can differ across universes. Refreshing the event page queries the committed receipt ledger; the display does not continuously poll.
