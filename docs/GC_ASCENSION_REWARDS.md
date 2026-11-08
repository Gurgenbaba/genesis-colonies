# Ascension reward candidates in the sandbox

> Measurement only. No game code, balance value, formula, migration or save game is changed. Every candidate is a **counterfactual rule set applied as a sandbox patch** of the canonical Nodebuster owner for the length of one simulated run (and restored afterwards); nothing here is a proposal. Analysis: `scripts/ascension_rewards_analysis.py`, tests: `tests/test_ascension_rewards_analysis.py`, `tests/test_simulator_isolation.py`, generated tables: `docs/GC_ASCENSION_REWARDS_REPORT.md`.

## 1. Question

The Ascension report (#559) found that the first reset loses money at every fixed threshold: one Ascension at L200 grants 1 AP and costs a rebuild of about 90 days. The aim here is a first reset that

1. **feels valuable straight away**,
2. **can be caught up in a manageable time**, and
3. **leaves `never` (keep building) a legitimate alternative** - without repeated resets becoming an unlimited production multiplier.

Per candidate we measure not only the income on the last day but cumulative production, payback time, AP access and the day on which a reset first brings a real advantage (income at least 110 % of `never` from then on).

## 2. Setup

* S1 (one planet), casual / active / optimizer, policy v2, UNI1 curve, 72 months, 381 + 63 scenarios (21 candidates x 7 arms x 3 styles + `never`). Everything is relative to `never` of the same style.
* **Policies** (new, the old `T<n>` is a treadmill that never gets deeper): `O<n>` = every mine is reset exactly once at depth n, then keeps building (the price of a *first* reset); `O<n>x<k>` = k resets per mine, then keeps building (a farm for AP and prestige); `L<n>+<d>` = a ladder, each further reset needs the previous record + d; `T200` = the treadmill. Resets run one mine at a time per planet.
* **Candidates** change one or more of: base rebuild cost (skills still subtract 5.5 % per Frugal rank down to the canonical floor of 35 %), the **restart level** (a share of the best depth, always below L200), a **fading** rebuild surge, AP per run, a **prestige** bonus (+x % output per Ascension of that mine, capped), and a strong **first Deep Yield rank** bought with the first AP. The surge fades to zero *at* the best depth on purpose: the canonical Legacy Reconstruction surge ends abruptly at the record, so one level above the record the mine's output falls by half (a test pins this), and a payback-ranked player simply refuses to cross it.
* Structure that stays true for every candidate: discounts apply only up to the best depth, permanent bonuses are either skills with maximum ranks or capped, the restart level stays below L200, and the simulator's invariants check that AP earned equals the awards *of the active rule* and AP spent equals the canonical skill costs.

## 3. Why the first reset loses (canonical rules, `O200`)

| | casual / active / optimizer |
|---|---|
| First reset on day | 409 / 364 / 349 |
| Income right after the reset (own income before = 1) | 0.62-0.63 |
| Back at the pre-reset income after | 87-109 days |
| Income vs `never` +1 / +2 years after the reset | 0.37 / 0.61 |
| Cumulative production vs `never` at 24 / 48 / 72 months | 0.28 / 0.60 / 0.74 |
| Payback | not within 72 months |

A reset at L250 or L300 is worse in every candidate (income at 48 months 0.61 / 0.50 vs 0.72 at L200): **the earlier, the better**. That contradicts the AP schedule, which pays more for waiting (1 / 3 / 6 AP at L200 / L250 / L300).

## 4. What moves the needle (cumulative production vs `never` at 48 months, `O200`, median of the styles)

| Lever | Candidate | 48 months | Payback |
|---|---|---:|---:|
| none (the game) | `canon` | 0.60 | - |
| **AP** +2 per run / 1 per 10 levels | `ap3` / `ap_steep` | 0.59 / 0.60 | - |
| strong first Deep Yield rank for 1 AP (+10 % output) | `rank1_yield` | 0.76 | - |
| fading rebuild surge +100 % | `fade100` | 0.64 | - |
| prestige +5 % / +10 % per Ascension (max 3) | `prestige` / `prestige10` | 0.70 / 0.77 | - |
| rebuild cost x0.40 | `cost40` | 0.76 | - |
| restart at 75 % of the record | `restart75` | 0.78 | - |
| restart 50 % + cost x0.50 + surge +50 % | `soft` | 0.82 | - |
| ... + prestige +5 % | `soft_p` | 0.92 | 1,631 days |
| restart 75 % + cost x0.40 + prestige +5 % + 2 AP | `fast_p` | 1.01 | 996 days |
| ... prestige +7 % / +8 % / +10 % | `fast_p7` / `fast_p8` / `fast_p10` | 1.05 / 1.08 / 1.13 | 740 / 656 / 526 days |
| restart 75 % + cost x0.40 + strong first Deep Yield rank | `rank1_fast` | **1.12** | **556 days** |
| restart 90 % + cost x0.40 + prestige +10 % + 2 AP | `keep90_p10` | 1.20 | 190 days |

* **AP are not the lever.** +2 AP per run changes nothing measurable (`abl_no_ap` is identical to `fast_p10` to the last digit): at L200 the first AP buy Frugal Rebuild ranks worth about −5.5 % rebuild cost each, and with a cheap rebuild they are worth nothing. Even with +2 AP the Overdrive gate (50 AP) needs 17 resets of one mine, the whole tree (339 AP) 113.
* **No single lever pays back.** Rebuild generosity (restart level, cost) shortens the lag but leaves a permanent gap; a permanent bonus alone cannot cover a 90-day gap.
* **The package is all three parts.** Ablations of `fast_p10` (48 months): without prestige 0.90, without the restart level 0.94, without the cost discount 1.00, with the full package 1.13.
* **Recovery.** With restart 75 % and cost x0.40 the empire is back at its pre-reset income after 26 days (17-30) instead of 89, the cliff shrinks from 0.63 to 0.70. `restart 90 %` gives a cliff of 0.86 and 11 days but makes resets almost free (section 6).

## 5. Design criteria

Thresholds are this analysis' operationalisation (medians over the styles): **C1** cliff leaves ≥ 2/3 of the income and the empire is back within 30 days; **C2** payback within 365 days (good) or 730 days (ok) for every style (judged on the slowest style; the first version of the code used the median, which changed one class only: `fast_p8` was "ok" at a median of 656 days but its optimizer needs 756); **C3** `never` stays legitimate: cumulative production at 48 months within 0.85-1.15 and no style above 1.25; **Guard** no multiplier by repetition: no style above 1.25 with treadmill, ladder or 4 / 8 resets per mine, and extra resets do not pay.

| Candidate | C1 | C2 | C3 | Guard | All |
|---|---|---|---|---|---|
| `canon` | no (0.63 / 89 d) | no | no (0.60) | yes | no |
| `fast_p10` | yes | ok (526) | yes (1.13) | **no** (farming pays for casual: 4 resets reach 1.57x) | no |
| `fast_p8` | yes | no (656; slowest style 756) | yes (1.08) | **no** (casual 1.39x) | no |
| `fast_p7` | yes | no (740) | yes (1.05) | **no** (casual 1.30x) | no |
| `keep90_p10` | yes | good (190) | no (1.20) | **no** (casual and active gain from farming, up to 1.76x) | no |
| `rank1_fast` | **yes** (0.70 / 26 d) | **ok (556)** | **yes (1.12)** | **yes** | **yes** |

Only `rank1_fast` satisfies all four: restart at 75 % of the record, rebuild cost x0.40 and a **one-time, non-stacking** strong first Deep Yield rank (+10 % output for 1 AP, per mine). Its numbers: income 0.87 / 1.02 / 1.13 of `never` 6 / 12 / 24 months after the reset, payback 556 days (461-631), income ≥ 110 % for good after 590 days (511-686), cumulative production 0.91 / 1.12 / 1.17 at 24 / 48 / 72 months. A reset at L250 / L300 pays back in 699 / 927 days instead.

## 6. The guard: repeated resets

* **The treadmill is self-destructive** in every candidate (income 1-5 % of `never` after 72 months): the mine never gets deeper than L200. Up to 4,170 AP are farmed this way (`keep90_p10`), and it buys nothing.
* **Farm, then climb is the real risk.** Stacking per-Ascension rewards (even capped) can be farmed *and it pays for the casual style*: with `fast_p10`, 4 resets per mine give casual 1.57x, active 1.16x, optimizer 0.87x of `never` at 72 months (a single reset: 1.20 / 1.18 / 1.02). `keep90_p10` pays for casual and active (1.76x / 1.36x). A reward that is bought once (`rank1_fast`: 4 resets 0.98x, 8 resets 0.77x) cannot be farmed: more resets only add lag.
* **Style asymmetry.** For every working candidate the casual style gains most (`rank1_fast`: 1.14 / 1.19 at 48 / 72 months vs 1.04 / 1.02 for the optimizer). Probable cause: the casual `never` path is bound by attention (its build queue runs 20 % of months 12-24 vs 73 % for the optimizer), so a cheap rebuild costs it less. This is a hypothesis, not measured here. It matters because a reward that is neutral for the optimizer is strongly positive for the casual player.

## 7. What this does and does not say

* The result is a **sandbox window**, not a proposal: roughly "keep three quarters of the depth, rebuild at 40 % of the cost, and give a single early permanent bonus around +10 %". Outside this window the first reset either never pays back or turns Ascension into the mandatory choice.
* The window is narrow and its boundaries are my thresholds. `fast_p10` is only excluded by the casual farm; `fast_p7` misses C2 by 10 days.
* The canonical Legacy Reconstruction surge has a cliff at the record (output halves one level above it, pinned by a test); the Breakthrough window removes it for 50 levels. Not touched.
* The AP schedule (more AP for waiting) and the economics (earlier is better) point in opposite directions.

## 8. Limits

* S1 only: one planet, two production mines. An 11-planet account has 22 mines; resets, prestige and farming there are not simulated.
* Fixed policies (`O`, `T`, `L`); a smarter timing might do better. AP order `rebuild_first` (`yield_first` for the first-rank candidates).
* The three styles differ in more than attention; the casual advantage is not explained by a measurement.
* Research-Lab Ascension, Stellar Forge, loot, Timekeeper not modelled. The baseline includes the outpost-XP defect (#556 not applied); it does not touch an S1 run.
* `abl_no_ap` showing zero effect means AP are worthless *in the first two years under these rules*, not that AP never matter (late-game skills are unchanged).

## 9. Harness changes in this step (simulator tooling, no game change)

* **Caches keyed by universe, one universe at a time.** The simulator's price and research-payment caches are keyed by the active endgame curve and colony gate, so a lookup under another curve cannot serve a stale price (the hazard found in the reconciliation); `SIM_LOCK` serialises scenarios, curve and lever patches and sandboxes per process, so threads cannot read each other's parameters; separate processes (the runners) are isolated by the OS. Covered by `tests/test_simulator_isolation.py` (9).
* **Policies `O<n>[x<k>]` and `L<n>+<d>`** next to `T<n>`; the AP invariant uses the owner's *current* rule so a candidate's awards are checked, not the canonical ones.

## 10. Reproduce

```bash
python scripts/ascension_rewards_analysis.py --workers 10 --out-json artifacts/ascension_rewards/latest.json --out-md docs/GC_ASCENSION_REWARDS_REPORT.md
python -m pytest tests/test_ascension_rewards_analysis.py tests/test_simulator_isolation.py -q
```

About 25 minutes on ten cores for all 444 scenarios (72-month runs); `--resume` adds candidates to an earlier JSON, `--quick` runs the active style only.
