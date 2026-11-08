# Ascension rewards at empire scale (11 planets, 22 mines)

> Measurement only. No game code, balance value, formula, migration or save game is changed. Every candidate is a **counterfactual rule set applied as a sandbox patch** of the canonical Nodebuster owner for the length of one simulated run (and restored afterwards); nothing here is a proposal. Analysis: `scripts/ascension_empire_fairness.py`, tests: `tests/test_ascension_empire_fairness.py`, `tests/test_simulator_isolation_stress.py`, generated tables: `docs/GC_ASCENSION_EMPIRE_FAIRNESS_REPORT.md`. Builds on `docs/GC_ASCENSION_REWARDS.md`.

## 1. Question

The reward study priced candidates on S1 (one planet, two production mines). Its only candidate that met all four checks, `rank1_fast` (restart at 75 % of the best depth + rebuild cost x0.40 + a one-time strong first Deep Yield rank for 1 AP), is a **per-mine** reward, and an 11-planet account owns 22 such mines. Does one mine, several parallel resets or the whole empire profit disproportionally - and does the reward stay un-farmable?

## 2. Setup

* S11 journeys (homeworld seed with eligible DNA, up to 11 planets, PL15 colony gate), casual / active / optimizer, policy v2, UNI1 curve, 72 months, 27 scenarios, everything relative to `never` of the same style. All invariants hold in every run.
* **Scopes** (policies of the journey simulator, every reset is a real canonical Nodebuster call): `M200` one single reset of one mine in the whole empire (the first mine that reaches L200); `G200` every mine once but only **one rebuild at a time in the whole empire** (a mine that is ready waits for its turn and keeps building, so it resets deeper than L200); `O200` every mine once, one rebuild at a time **per planet** (planets in parallel - the empire resets as it matures); `O200x4` four resets per mine (the farm); `L200+25` a ladder.
* Candidates: `canon` (the game, `O200` only), `rank1_fast` (all scopes), `fast_p10` (the stacking-prestige candidate that S1 showed to be farmable: `O200` and `O200x4`).

## 3. Results for `rank1_fast`

Median over the three styles (range in brackets), cumulative production vs `never`.

| Scope | Resets | Max parallel rebuilds | Worst empire income vs never | Payback (days after the first reset) | 24 / 48 / 72 months |
|---|---:|---:|---:|---:|---|
| `M200` one mine | 1 | 1 | 0.92 (0.89-0.93) | 661 (518-822) | 0.99 / 1.00 / 1.00 |
| `G200` serial | 17 (14-19) of 22 | 1 (1-2) | 0.81 (0.75-0.82) | only the active style (1,293) | 0.86 / 0.91 / 0.92 |
| `O200` whole empire | 22 | 3 (3-4) | 0.65 (0.57-0.70) | 641 (633-802) | **0.88 / 1.10 / 1.17** |
| `O200x4` farm | 88 | 32 | 0.30 | - | 0.35 / 0.76 / 0.96 |
| `L200+25` ladder | 172 | 11 | 0.44 | - | 0.45 / 0.20 / 0.13 |

For comparison `canon` (the game) on the whole empire: 0.30 / 0.58 / 0.73 (S1: 0.28 / 0.60 / 0.74).

## 4. Findings

* **The reward scales linearly, not super-linearly.** The whole empire reaches 0.88 / 1.10 / 1.17 at 24 / 48 / 72 months against 0.91 / 1.12 / 1.17 on one planet (S1); no style is above 1.19. Twenty-two mines do not multiply the effect. Scale check: passed.
* **One reset is invisible at empire level.** A single reset (`M200`) costs the empire 7-11 % income at its worst point (the reset mine itself drops to 0.70 of its income and is back after 22-31 days, as in S1) and ends exactly level with `never` (1.00 from 48 months). The "first reset feels valuable" criterion holds for the mine, not for the empire; the empire only profits from a **campaign** that resets most mines.
* **Parallel beats serial by a wide margin (+0.19 at 48 months).** With one rebuild at a time in the whole empire the 22 resets take longer than the horizon allows (14-19 done after 72 months), mines that wait keep building and reset deeper, and two of three styles never pay back. Resetting every planet as soon as it is ready is simply the best policy - a dominant strategy, not a decision (at peak 3-4 mines rebuild at once).
* **The whole-empire campaign hurts most in the first year.** Worst empire income is 0.65 of `never` (0.57 casual) and the cumulative-production payback needs 641 days (633-802); real advantage (income >= 110 % of `never` for good) starts 723 days after the first reset.
* **The style asymmetry flips with scale.** On one planet the casual style gained most (1.14 vs 1.04 for the optimizer at 48 months, payback 461 days, fastest). In the empire the casual style gains least: 1.03 / 1.11 / 1.10 at 48 months, **payback 802 days (active 633, optimizer 641)**, deepest dip 0.57 (day 450 vs 0.70 / 0.65). Descriptively: the casual reset campaign runs 585 days (day 398 to 983; optimizer 721 - 339 = 382), only 13 of 22 mines are reset after 24 months (18 active, 22 optimizer), and its 11th world arrives on day 641 (444 optimizer). The cause is **not measured**; one hypothesis is that the casual build queue has to serve both the rebuilds and the colony pipeline.
* **Repeating is strictly dominated.** Four resets per mine give 0.35 / 0.76 / 0.96, the ladder destroys the economy (0.13 at 72 months). The guard is satisfied, but for the design intent ("repeated Ascensions should become increasingly strategic decisions") it means that with this reward there is **no reason ever to reset a mine twice**: Ascension is a one-time campaign.
* **The farmable candidate stays farmable at scale, for a different style.** `fast_p10` with four resets per mine reaches 0.98 / 1.33 / 1.19 (casual / active / optimizer) at 72 months against 1.07 / 1.17 / 1.17 with one: the active style gains +0.16 and ends above the 1.25 limit, the casual style (which profited most on S1) now loses. A stacking per-Ascension bonus remains a multiplier, only the beneficiary changes.

## 5. Verdict for `rank1_fast`

| Check (this analysis' thresholds) | Result |
|---|---|
| Scale: the whole empire within 0.85-1.15 at 48 months, no style above 1.25 | yes (1.10, highest style 1.19) |
| Scope: no scope pushes a style above 1.25 | yes |
| Guard: farming and the ladder do not pay | yes |
| Payback within 730 days for **every** style | **no** - casual 802 days |
| **All** | **no** |

`rank1_fast` stays what it was called: a **reference candidate**, not a solution. It is bounded and un-farmable and it scales, but at empire scale the casual style misses the payback window, a single reset is economically invisible, and repeating a reset is never worth it. These are exactly the points the next step (variants that pay back within 6-12 months without making `never` unattractive, and a bounded reason for a second reset) has to address.

## 6. Limits

* **One homeworld seed** (eligible DNA), one reward family, fixed policies. A smarter selective policy (reset only the most mature planets, or only the newest) is not modelled; `M200` resets whichever mine reaches L200 first.
* `G200` is serial in the sense of the policy only (ready mines wait and keep building); a player who holds a mine at L200 while waiting would reset earlier and might do better.
* The empire timeline uses the PL15 colony gate and the baseline includes the outpost-XP defect (#556 not applied); it affects colony founding, not the mine rules priced here. Expedition XP, Research-Lab Ascension, Stellar Forge, loot and Timekeeper are not modelled.
* The thresholds are this analysis' operationalisation; the casual explanation is a hypothesis.
* 72 months of the empire are measured; the lead of `rank1_fast` (1.17) is still growing slowly at the end (income ratio 1.14-1.22), so the long-run level is not pinned down.

## 7. Harness changes in this step (simulator tooling, no game change)

* New scope policies `M<n>` and `G<n>` next to `O<n>`, `L<n>+<d>`, `T<n>` (`parse_asc_policy`, `asc_target`, `asc_stagger_blocked`), covered by unit tests (stubbed multi-planet journeys).
* **Correction of the S1 study:** its payback class was computed on the *median* style although its text said "for every style". It is now judged on the slowest style, with a test. The only class that changes is `fast_p8` (ok -> no: median 656 days but its optimizer needs 756); the verdict for `rank1_fast` (slowest style 631 days) is unchanged. The generated S1 report and the curated S1 table were updated.
* **Isolation stress tests** (`tests/test_simulator_isolation_stress.py`, 5) with a new self-check `player_journey_sim.universe_probe`: four universes (legacy / UNI1 curve x PL15 / PL10 gate) hammered by 8 threads x 30 iterations, by a single reused worker process running ten universes in a row, by four parallel processes, and by whole `run_scenario` calls back to back; every universe sees exactly its own key, gate and price, and the process is back at its defaults afterwards.

## 8. Reproduce

```bash
python scripts/ascension_empire_fairness.py --workers 11 --s1-json artifacts/ascension_rewards/latest.json --out-json artifacts/ascension_empire/latest.json --out-md docs/GC_ASCENSION_EMPIRE_FAIRNESS_REPORT.md
python -m pytest tests/test_ascension_empire_fairness.py tests/test_simulator_isolation_stress.py -q
```

About 14 minutes on 11 cores for the 27 scenarios (72 months, S11); `--quick` runs the active style only; `--resume` adds scenarios to an earlier JSON.
