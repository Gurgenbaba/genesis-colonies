# GC-ENDGAME-ECO-REBASE-002 — Coordinated Endgame Economy V2

Status: implementation / shadow-first cutover

## Why

The old high-level mine curve `base × level × 1.075^level` makes production,
upgrade prices and cost-derived ranking explode together. A production-only fix is
unsafe because the same reference curve feeds upgrade pacing and research costs,
while building score historically follows cumulative live upgrade costs.

V2 therefore changes **Production + new Costs + Research scaling + Progression Score**
as one coordinated cutover. `GC_ENDGAME_ECONOMY_MODE` remains the fail-closed
operator gate:

- `legacy`: historical gameplay and ranking;
- `shadow`: historical gameplay/ranking plus V2 comparison tooling;
- `active`: the coordinated V2 rules below.

**Never enable `active` with the old L650 candidate pivot.** The final V2 candidate
uses pivot **L120** and tail power **q=2**.

## Production V2

For pivot `P=120`, historical mine output `f(P)`, `x=L-P`, and
`s = 1/P + ln(1.075)`:

```text
f_v2(P+x) = f(P) × (1 + s×x/2)^2
```

It is value- and derivative-continuous at L120, monotone, unbounded, and replaces
the permanent exponential with polynomial long-run growth.

Approximate output relative to L120:

| Level | V2 / L120 |
|---:|---:|
| 120 | 1.00× |
| 150 | 4.88× |
| 200 | 17.86× |
| 300 | 68.21× |
| 500 | 266.5× |
| 650 | 500.6× |
| 1000 | 1331× |

`legacy` and `shadow` continue returning the old production values.

## Mine Cost V2

Through L120 the historical GC-821 ROI anchors are unchanged. Above L120:

```text
H(L) = 2000h × (L / 120)^0.70
```

The live upgrade-cost owner continues to price mines from the canonical production
delta; therefore in `active` mode the delta is V2 and the reference horizon is V2.
No event, commander, directive, energy or temporary production modifier enters the
price anchor.

Reference horizons:

| Level | Hours | Days |
|---:|---:|---:|
| 120 | 2,000 | 83.3 |
| 200 | ~2,860 | 119.2 |
| 300 | ~3,798 | 158.3 |
| 650 | ~6,526 | 271.9 |
| 1000 | ~8,823 | 367.6 |

## Research V2

`mining_tech`, `crystal_tech`, and `drone_tech` keep their historical linear effect
through L120. In `active` mode only, the effective production-research level above
L120 becomes:

```text
L_eff = 120 + 120 × ln(1 + (L - 120) / 120)
```

This is continuous with derivative 1 at L120, remains unbounded, and has diminishing
marginal returns afterwards. `legacy` and `shadow` remain linear.

Research cost reference income is obtained from the canonical mine reference. Thus
`active` research prices follow the V2 mine tail rather than the old exponential.

## Score V2

Progression score is versioned independently from live prices. The owner is
`game/progression_valuation.py`, with valuation version `v2`.

### Buildings

`building_progression_value_v2(building, level)` does not call `get_upgrade_cost()`
or `power_upgrade_cost()`. It freezes the V2 baseline so a future balance-price edit
cannot retroactively rewrite historical progression ranking.

- L1–L120: same reference valuation as the cutover baseline.
- Mine L121+: cumulative V2 reference production delta × V2 investment horizon,
  using the frozen per-building resource split.
- Non-mine buildings: frozen cutover reference curves.

Reference check: one Ferronit Mine L650 is approximately **203 billion building
points**, rather than ~`3.8×10^25` under the old cost-derived valuation.

### Research

Account-research progression valuation is frozen in the same module. Through L120
it reproduces the cutover baseline; above L120 its reference income uses the V2 mine
tail. This prevents future research-price edits from rewriting already-earned rank.

### Liquid resources

`resource_score` remains visible as the **wealth** dimension but is excluded from
`total_score` in `active` mode. `legacy` and `shadow` intentionally keep the old
behavior until the atomic cutover.

Progression total in V2:

```text
total_score = building + research + fleet + defense + evolution
```

Destroyed score remains military prestige only and is not added to progression.

## Shadow ranking

Run read-only comparison before activation:

```bash
python scripts/endgame_economy_shadow_report.py --output /tmp/endgame-v2-shadow.json
```

The report includes per player:

- V1/V2 total score;
- V1/V2 building and research components;
- V1/V2 rank and rank delta;
- liquid wealth separately;
- Commander-SP claimed milestones and old/new unclaimed eligibility;
- all changed score-corridor outcomes for the 5× noob-protection rule (bounded
  examples plus exact changed-pair count).

The report never writes `player_scores`.

## Atomic cutover procedure

1. Deploy this code with `GC_ENDGAME_ECONOMY_MODE=shadow`, pivot `120`, q=`2`.
2. Run and review the complete shadow ranking report on Production data.
3. At cutover timestamp **T**, while still on V1 gameplay, settle outstanding
   resource ticks through T using the normal authoritative resource/tick path.
4. Existing queued jobs keep their stored paid-cost snapshots. Do not reprice or
   refund them from V2 formulas.
5. Switch `GC_ENDGAME_ECONOMY_MODE=active` with pivot `120`, q=`2`.
6. Recompute every player's score with V2 and run one full rank rebuild.
7. Verify ranking, 5× PvP corridors, Commander claims, economy endpoints and
   high-level storage before reopening normal operations.

## Storage contract

A rebase must **never delete already-held resources** merely because a recalculated
capacity is lower. Existing overflow remains. Production credits zero additional
units for that resource until the balance is below the current capacity again.
Trader/Scrapyard overflow behavior stays unchanged.

## Commander Skill Points

Commander milestone claims are persisted independently in
`player_commander_sp_claims`; `skill_points_earned` / `skill_points_unspent` are not
re-derived downward from score. V2 may change eligibility for **unclaimed** future
milestones, but already claimed points are never revoked.

## Rollback

Before activation, rollback is simply `shadow` or `legacy`. After an active score
rebuild, reverting gameplay mode also requires rebuilding player scores under the
selected legacy rules so cached ranking rows and noob-protection inputs agree.
