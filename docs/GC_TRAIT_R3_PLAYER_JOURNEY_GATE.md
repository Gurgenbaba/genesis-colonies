# GC — Trait R3: 6/12-Month Player-Journey Gate

**Status:** Measurement design only. No live gameplay changes.  
**Baseline:** `b0d0ba254edf3f59b57820cef628040d2d4a4f3a` (#553).  
**Owner:** `game/planet_evolution/` for DNA/progression, `game/mine_evolution/` for mine Ascension, `EffectResolver` for effects.

## What the existing evidence actually proves

- `scripts/audit_long_horizon_economy.py` is a **record-mine upper-bound audit**, not a player journey. Its documented 6/12-month levels are 237/273 (one mature world) and 508/705 (11 mature worlds, 100% pooled). Do not present these as typical account outcomes.
- `scripts/fresh_account_progression_sim.py` starts from starter resources and models early buildings/research, but only reports the first 30 days and lacks DNA/Ascension, full colony expansion, expedition/loot, Timekeeper and decisions.
- `docs/ENERGY_V2.md`: global Energy V2 Candidate A is **simulation-only**. Solar >L200 via the existing mine endgame Buildings queue is the deployed narrow bridge, not the global rework.
- `docs/GC_TRAIT_SYSTEM_V2.md`: R2C lab scans cost `10_000 × level` metal + `5_000 × level` crystal, add 120 XP with a per-world rolling 24h cooldown. R2D repairs stale L15 reveal tier without reroll. R3 resonances are **not shipped**.
- The existing endgame audit identifies late-game static-hull/Forge throughput as a candidate sink problem. Do not globally alter hull costs before an end-to-end military sink analysis.

## Measurement contract (implement as isolated follow-on script)

Use **the existing canonical server functions** for all economy, cost, construction/research timers, XP, reveals, Ascension AP and mechanics. Do not duplicate or approximate formulas in a new owner. Execute in a sandbox, never against a live database.

For each scenario record a **daily** row, with summary checkpoints at day 7, 30, 90, 182/183 and 365. Define “month” as six and twelve calendar-month-equivalent checkpoints (182.5/365 days) to match the existing audit. Disclose any rounding convention.

### Topologies

| Case | Starting point | Goal |
|---|---|---|
| S1 | Fresh account, one homeworld, no additional colonization | Show solo progression and structural stalls |
| S11 | Fresh account, legally expands from one to eleven worlds | Include colony timing, colony costs, infrastructure and fleet transport; **do not** grant eleven mature worlds at day 0 |
| U11 | Existing optimistic 11-world pooled upper bound | Preserve as control only; not a player route |

S11 must validate the **actual universe colony limit** from settings; if 11 worlds are unavailable under a given preset, return `scenario_unavailable` rather than silently bypassing the cap.

### Playstyle variants

For both S1 and S11 measure:
1. **Casual:** two action windows/day, conservative idle/queue utilization; no premium or random drops.
2. **Active:** four action windows/day; deterministic free login/Timekeeper rewards separated in ledger.
3. **Optimizer:** optimistic decisions, near-zero avoidable idle, no paid boosts; report separately from causal/human expectation.

These are scheduling assumptions, not guarantees of a real user's behavior. Each decision and skipped time interval must be reconstructible.

### Mandatory measured outputs

- Highest/median mine depth; effective M/C/fuel production per world and empire; energy demand/supply and shortage time by hot/mid/cold slot.
- Resource spend broken out by mines, solar, storage, research, colony expansion, transport, DNA analyses and Ascension rebuild.
- Build/research queue occupancy, wall-clock waiting for costs, transport waiting, capped storage time and wasted production.
- Day of each colony unlock and establishment; planet XP/level/reveal tier; DNA scan count/cost/cooldown; known vs hidden traits; Ascension depth, AP earned and spent.
- Premium and free accelerators in **separate** ledgers, default paid=0; no assumed loot jackpot or DNA reroll.
- Unlock deadlocks and any 'unreachable' mechanic; first occurrence date, blocking condition and recovery path.
- Median and worst-world gap across S11 to detect one ultra-developed world carrying ten unusable colonies.
- Sensitivity run without rare DNA traits to prove core progress is possible.

All money/resource arithmetic should preserve the precision and integer rounding of the authoritative owners. Compare simulations via a seeded/fixed policy; record code SHA, settings digest, initial state and decision-policy version.

## Trait R3 candidate constraints (not live values)

1. Synergy requires a **revealed trait** plus a **genuinely active specialization**; unmet/hidden gates must yield zero resonance.
2. Trait + specialization may reduce one domain's duration or consumption but must not change the mine's production exponent or reroll DNA.
3. A suggested first tuning envelope for **testing only** is 5–12% reduction to one qualified planet-specific timer, with a strict combined resonance cap; use actual simulations to choose final values.
4. Alternative non-rare routes must exist for critical unlocks; rare traits are optimization/specialization, not mandatory global gates.
5. Existing planet mechanics are recomputed on load/milestone in the canonical transaction with explicit cache invalidation; ownership checks before write-on-read.
6. R3 is blocked until S1/S11 simulator output and regression tests show no exploit, critical softlock or large uncontrollable multi-world multiplier.

## Acceptance criteria for next implementation PR

- Run a reproducible S1/S11 182.5/365d comparison from a **fresh** account; output JSON + readable Markdown summary, with CLI and tests.
- Outputs distinguish **actual simulated trajectories** from the existing upper bounds, and specify which gameplay loops were not modelled.
- Enforce S11 legal colonization (limit, costs, timing); enforce DNA scan ownership/cooldown and L3/L15 tier invariants.
- Core state must not contain negative resources, duplicate completes, free queue skips or hidden trait leakage.
- At least one hot/mid/cold world run; flag prolonged `energy_ratio < 0.95` and `storage_full` as measurable bottlenecks, not automatically failures.
- Compare zero-trait, common-trait and candidate resonance scenarios without enabling R3 live.
- Existing `tests/test_long_horizon_economy_audit.py` and `tests/test_gc829_fresh_account_progression.py` remain green.
- No new gameplay DB tables, no duplicate production formulas, no live deployment from this measurement-only slice.

## Decision gate

Do not merge live resonance modifiers until both real player trajectories and the optimistic upper bound are reported side by side, and the effect on 6/12-month rank dispersion, queue utilization and solo-vs-eleven disparity is quantified.
