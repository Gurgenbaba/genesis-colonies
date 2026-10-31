# GC-VOIDFALL-007 — missions explain themselves (2026-10-31)

## Problem

In the live /login-rewards surface, objectives displayed only 0/N progress and an item name. Players could not tell which completed action counted, which page to use, or whether a 15-minute booster was a timed percentage or a real time credit. "Einsatzbereitschaft" has five legal activity sources but its UI didn't show those.

## Implementation

- All three daily mission cards now have a concrete explanation of the **server-verified** condition.
  - **Riss-Erkundung**: two resolved fleet expeditions (`activity_xp_log.source_key=expedition` on expedition resolution; merely dispatching doesn't count).
  - **Kolonie verstärken**: one **finished** building upgrade (`building_finish`).
  - **Einsatzbereitschaft**: three completed actions across `expedition`, `building_finish`, `account_research_finish`, `spy`, `recycle`. Actions are shared with the two other missions. Five source counters come from the **same already-loaded** activity snapshot, so this adds no query.
- Action links lead to the existing Fleet / Buildings / Research routes, instead of requiring players to hunt through the UI.
- Welcome, mission, convergence milestone, alignment choice and discovered rewards explain the **actual** item benefits with compact descriptions:
  - 15-minute build/research boosters = 900 seconds of real queue/Timekeeper time credit (not a +% timed buff).
  - Expedition loot booster = +25% loot over 24h **after activation**.
  - Containers are opened in inventory and give random rewards; no invented item drop guarantees.
- All 8 existing languages receive the same keys. Additional CSS only; **no extra images, client polling or network endpoints**.
- Existing claim security, rates, milestone thresholds (20/40/70, alignment at 40), discovery odds, event expiry and receipts are unchanged.

## Verification

Two new unit/contract tests validate activity breakdown and reward semantics, all localized text keys and the navigational template contracts. Standard LiveOps, smoke, i18n, PG and Browser Sentinel release gates apply to DEV and UNI1. Avoid any prelaunch reset.
