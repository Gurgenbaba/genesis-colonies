# Ascension milestones: First Awakening, record tiers and repeat resets

> Measurement only. No game code, balance value, formula, migration or save game is changed. Every candidate is a **counterfactual rule set applied as a sandbox patch** of the canonical Nodebuster owner for the length of one simulated run (and restored afterwards); nothing here is a proposal, and one candidate deliberately lifts a canonical design invariant (section 5). Analysis: `scripts/ascension_milestones_analysis.py`, tests: `tests/test_ascension_milestones_analysis.py`, generated tables: `docs/GC_ASCENSION_MILESTONES_S1_REPORT.md` (one planet) and `docs/GC_ASCENSION_MILESTONES_S11_REPORT.md` (11 planets). Builds on `docs/GC_ASCENSION_REWARDS.md` and `docs/GC_ASCENSION_EMPIRE_FAIRNESS.md`.

## 1. Question and acceptance

`rank1_fast` is a reference candidate with two weaknesses: its first reset pays back in 631 days (one planet) to 802 days (empire), and a second reset is strictly worse than none. The aim of this step, as asked:

* **A - First Awakening:** a one-time, stronger bonus at the first reset of a mine, for an earlier economic benefit.
* **B - Reconstruction milestones:** better rebuild options after the second and third reset, so that repeating is worthwhile.
* **C - Depth Breakthrough:** rewards tied to new **record depths** instead of reset counts, so that resetting the same mine at L200 again earns nothing.

Acceptance, operationalised in `criteria` (thresholds are this analysis' choice and printed in the reports): **K1** the first reset pays back within 6-12 months (365 days) for every style, judged on the slowest; **K2** the second reset adds at least 0.02 cumulative production (median style, none loses more than 0.02) and the third at least 0; **K3** no dominant farm over 72 months: four resets per mine at L200 do not beat the best sensible policy of any style by more than 0.02, and uncapped ladders stay below 1.25; **K4** `never` stays legitimate: median first-reset policy within 0.85-1.15 at 48 months and no style above 1.25 with its best sensible policy (first reset, metal mines only, two or three resets, or one late reset at L250 / L300).

## 2. Setup

* S1 (one planet, two mines): 35 rule sets, 774 runs. S11 (homeworld seed with eligible DNA, up to 11 planets / 22 mines, PL15 gate): the 7 leading rule sets, 135 runs. Casual / active / optimizer, policy v2, UNI1 curve, 72 months; everything relative to `never` of the same style. All invariants hold in every run (the AP check follows the owner's current rule, including the record-based one).
* Policies: `O200` every mine once at L200; `P200` only the metal mine of every planet (selective); `H200` only the homeworld; `M200` one single mine in the empire; `L200+50x2` / `x3` a second / second and third reset, each after +50 levels over the record; `O250` / `O300` one late reset; `O200x4` the farm (four resets per mine at L200); uncapped ladders `L200+50`, `L200+25`.
* Five rounds of rule sets, each reacting to the previous one: **A** (`aw15`, `aw20`, `aw15_soft`, `aw10_soft`), **A+C** record tiers (`c_*`), **round 2** generous rebuilds that improve per tier plus record-based AP (`m1`..`m8`), **round 3** keeping a share of the record (`n1`..`n5`), **rounds 4-5** budget sweeps (`q1`..`q5`, `r1`..`r4`). References: `canon`, `rank1_fast`, `fast_p10`, `keep90_p10`.

## 3. How the rules work (sandbox)

* **Record tier** = `(best depth - 200) // 50`, capped. `best_depth` only moves when a reset happens at a new depth, so everything keyed to the tier is a function of the **record**, never of the number of resets.
* **Awakening:** a permanent output bonus once a mine has ascended; one-time per mine, never stacks, costs no AP.
* **Tier rewards** (per tier, capped): output, kept share of the record on restart, rebuild cost, rebuild time.
* **AP only for record progress** (`ap_by_record`): a reset awards `points_for_depth(level) - points_for_depth(previous best)`, 0 at or below the record. Pinned by a test through the real owner: resets at L200, L250, L250, L200, L300, L260 award 1, 2, 0, 0, 3, 0 AP; the total depends only on the record (6 AP). Without this rule a deep record plus a lifted restart ceiling would be a near-free AP loop.
* **Restart ceiling:** the canonical owner restarts every reset **below L200**. Candidates `n*`, `q*`, `r*` lift that and keep a share (85 %) of the record instead; `aw*`, `c_*`, `m*` keep the canonical ceiling.

## 4. Findings

### 4.1 The first reset (A): an awakening of 7-8 % plus a cheap rebuild gets it into the 6-12 month window

S1, slowest style (median in brackets), cumulative production vs `never` at 24 / 48 / 72 months:

| Rule set | Payback (days) | Cum. production 24 / 48 / 72 mo |
|---|---:|---|
| `canon` (the game) | never | 0.28 / 0.60 / 0.74 |
| `rank1_fast` (reference) | 631 (556) | 0.91 / 1.12 / 1.17 |
| `aw15` (+15 %, restart 75 %, cost x0.40) | 421 (356) | 1.00 / 1.25 / 1.27 |
| `aw10_soft` (+10 %, restart 85 %, cost x0.30) | 351 (306) | 1.02 / 1.18 / 1.20 |
| `m1` (+8 %, restart 85 %, cost x0.30, time x0.70) | 301 (266) | 1.03 / 1.15 / 1.17 |
| `r4` (+7 %, same rebuild) | 346 (310) | 1.01 / 1.12 / 1.15 |

The payback is bought with two things: a cheap, fast rebuild (cliff 0.79, back at the old income after 12 days instead of 26) and a permanent bonus. A bigger bonus pays back sooner but breaks K4 (`aw15` 1.25 median at 48 months, `aw20` 1.38). An awakening without the cheaper rebuild is not enough (`aw15` 421 days) and a cheaper rebuild without the awakening never pays back (`m8`: 0.95).

### 4.2 Repeat resets (B): only worthwhile if a reset keeps a share of the record

| Rule set | Gain 2nd reset | Gain 3rd reset | What changed |
|---|---:|---:|---|
| `rank1_fast` | -0.09 | -0.19 | reference |
| `m1` | +0.02 | -0.08 | tiers: +4 % output, cost and time shrink per tier; canonical ceiling (restart below L200) |
| `m7` | -0.06 | -0.11 | m1 without the output reward per tier: cheaper rebuilds alone do not pay |
| `n3` | +0.05 | +0.01 | keep 85 % of the record (+2 pp per tier), +6 % awakening, tiers as m1 |
| `r1` | +0.03 | +0.02 | +7 % awakening, +3 % per tier (max 2), rebuilds -8 pp cost / -15 pp time per tier |
| `r4` | +0.02 | +0.01 | as r1 with +2.5 % per tier |

*Gain* = cumulative production vs `never` at 72 months of "one more reset" minus "stop before it" (median style). The reason is structural: with the canonical ceiling every reset restarts below L200, so a deeper record means a longer climb (record minus 199 levels at ever higher prices) and a deeper output dip, while the reward stays small. Keeping a share of the record makes the dip a constant fraction (cliff 0.79 every time) and lets +2.5-4 % per tier pay. For `r1` / `r4` the second reset pays back after 743 / 888 days (median) and the third after 581 / 721 days: a long-term decision, not a quick win.

### 4.3 No dominant farm (C): by construction and measured

* A reset without a new record earns no AP and no tier; the awakening is one-time. Farm `O200x4` is **-0.08 to -0.23 below the best sensible policy** for every candidate and style (`r4`: -0.17 / -0.17 / -0.10 on one planet, -0.16 / -0.16 / -0.13 on 11 planets); naive ladders (`L200+25` every 25 levels, uncapped `L200+50`) end between 0.57 and 1.12 of `never` (`r4`, 72 months), far below the best policy for active and optimizer.
* AP are still not the lever: `m5` (canonical AP per reset) is numerically identical to `m1` (AP by record); the rule is a safety property, not a source of the effect.

### 4.4 A side effect to decide on: waiting pays

With record tiers, one late reset collects several tiers at once and keeps 88-91 % of a deep record. For `r4` on S1: `O200` 1.15 / 1.15 / 1.04, `O250` 1.21 / 1.19 / 1.06, `O300` 1.25 / 1.22 / 1.05 (casual / active / optimizer, 72 months), and the late reset pays back in 22-77 days (L300) instead of 226-346. The earlier finding "the earlier, the better" (canonical rules) is therefore reversed; repeating is not required to get the whole reward (budget at most +12 %), and "reset immediately" is no longer the best choice. That is a timing decision as asked for, but it also means the first reset is *valuable* (payback within a year) without being *urgent*.

### 4.5 The window is razor thin

`r4` meets all four checks in S1 and sits on the boundary of each: slowest payback 346 of 365 days, second-reset gain 0.022 of 0.02, best response of the casual style 1.249 of 1.25. Its neighbours fail one check each: `r1` (+3 % per tier) best response 1.27 (K4), `r2` (one tier only) third reset -0.06 (K2), `r3` (+9 % awakening, +2 % per tier) K2, `n3` / `q5` K4 (1.28 / 1.31) or K1. The repeat requirement (K2) and the cap on the strongest style (K4) pull against each other because the same reward is worth far more to the casual style (second reset +0.05) than to the optimizer (-0.006).

### 4.6 Empire scale (S11): K2-K4 hold, the casual first reset is slow unless it starts with the metal mines

`r4`, 11 planets / 22 mines:

| | Casual | Active | Optimizer |
|---|---:|---:|---:|
| `O200` whole empire: payback (days) | **507** | 343 | 356 |
| `O200`: deepest empire dip vs `never` | 0.80 | 0.84 | 0.76 |
| `O200`: cum. production 48 / 72 mo | 1.07 / 1.07 | 1.11 / 1.14 | 1.11 / 1.15 |
| `P200` only the metal mines: payback (days) | **329** | 259 | 287 |
| `P200`: cum. production 48 / 72 mo | 1.07 / 1.07 | 1.08 / 1.09 | 1.08 / 1.08 |
| `H200` homeworld only / `M200` one mine: 72 mo | 1.00 / 1.01 | 1.02 / 1.00 | 1.01 / 1.00 |
| Gain 2nd / 3rd reset | -0.02 / -0.02 | +0.02 / +0.02 | +0.02 / +0.01 |
| Best response 72 mo | 1.09 | 1.20 | 1.18 |

* **K2, K3, K4 hold at empire scale**; farming is 0.13-0.16 below the best policy, no style exceeds 1.20.
* **K1 holds for active and optimizer; the casual whole-empire campaign needs 507 days.** Starting with the metal mines only (`P200`) brings the casual payback to 329 days at the same 48- and 72-month level (1.07) - the crystal mines add risk, not value, for that style. So the first step passes for every style if it is allowed to be selective (`K1 best start`), and fails in the strict reading.
* Selective resets never exceed 1.12: a reset of the homeworld or of one mine is economically neutral (1.00-1.02), as in the empire study.
* The style asymmetry flips with scale again: on one planet the casual style gains most from repeats, in the empire it gains least (second reset -0.02). Cause not measured.

### 4.7 Acceptance summary (strict K1 in brackets: best start)

| Rule set | S1 K1 / K2 / K3 / K4 | S11 K1 / K2 / K3 / K4 |
|---|---|---|
| `rank1_fast` | no / no / yes / yes | no (no) / no / yes / yes |
| `aw10_soft` | ok / no / yes / no | no (ok) / no / yes / no |
| `m1` | ok / no / yes / no | no (ok) / no / yes / yes |
| `r1` | ok / yes / yes / no | no (ok) / yes / yes / yes |
| `r4` | ok / yes / yes / **yes** | no (**ok**) / yes / yes / yes |

## 5. Candidate `r4` ("Record Milestones", sandbox only)

* Awakening: +7 % permanent output on a mine once it has ascended once (no AP, one-time).
* Rebuild: keep 85 % of the record depth (the canonical "restart below L200" ceiling is lifted), rebuild cost x0.30, time x0.70, inside the existing rebuild window up to the record.
* Record tiers every 50 levels above L200, at most 2: each +2.5 % output, +3 pp of the record kept (85 -> 88 -> 91 %), -8 pp rebuild cost, -15 pp rebuild time (floors 10 % cost, 20 % time).
* AP only for record progress. Total permanent output at most +12 %.

It is the first rule set that passes K1-K4 on one planet and K2-K4 plus the best-start K1 on 11 planets, not a recommendation: it is on the boundary of every check, and it lifts a canonical invariant (restart below L200) that exists to make a reset always lead below the activation level. In the sandbox the AP rule and the record tiers close the loop that invariant guards against; other systems that read mine levels (ranking score, achievements, world-boss and trade tooling) are not modelled.

## 6. Limits

* Fixed reset policies; a smarter timing (for example resetting a mine when its marginal payback is best) might do better, and the casual style might avoid the slow whole-empire start by itself.
* S1 has two mines; S11 uses one homeworld seed and the PL15 gate; the baseline includes the outpost-XP defect (#556 not applied). Research-Lab Ascension, Stellar Forge, loot and Timekeeper are not modelled.
* Thresholds are this analysis' operationalisation; with different limits another neighbour of `r4` could be the best set. The tier step (50), the caps and the floors are sandbox values; only the S1 screen covered all 35 rule sets, S11 the seven leading ones.
* The casual-vs-optimizer asymmetry and its reversal at empire scale are descriptions, not explained.
* `O250` / `O300` were run for the main candidates only (`canon`, `rank1_fast`, `aw10_soft`, `m1`, `r1`, `r4` on S1; `rank1_fast`, `r4` on S11); other candidates' best response uses the arms they have.

## 7. Harness changes in this step (simulator tooling, no game change)

* Policies `P<n>` (metal mine of every planet), `H<n>` (homeworld) and a reset cap per mine for ladders (`L200+50x3`); `parse_asc_cap`.
* Sandbox rules: awakening, record tiers (output, kept share, cost, time), restart ceiling, `ap_by_record` (the AP rule reads the mine's record through the `ascend_mine` wrapper), base rebuild time and floors. The simulator's AP invariant evaluates the owner's current rule with the previous record (`expected_ascension_points`).
* 22 tests: rule patches and restoration, AP through the real owner, selective and capped policies, marginal value of repeat resets, acceptance logic on synthetic series, report round trip.

## 8. Reproduce

```bash
python scripts/ascension_milestones_analysis.py --topology S1 --workers 11 --out-json artifacts/ascension_milestones/s1.json --out-md docs/GC_ASCENSION_MILESTONES_S1_REPORT.md
python scripts/ascension_milestones_analysis.py --topology S11 --workers 11 --candidates canon,rank1_fast,fast_p10,aw10_soft,m1,r1,r4 --resume artifacts/ascension_empire/latest.json --out-json artifacts/ascension_milestones/s11.json --out-md docs/GC_ASCENSION_MILESTONES_S11_REPORT.md
python -m pytest tests/test_ascension_milestones_analysis.py -q
```

About 25 minutes of compute for the S1 screen (738 runs, plus 36 late-reset runs added with `--candidates ... --arms O250,O300`) and 41 minutes for the S11 set on 11 cores; `--resume` adds rule sets or arms to an earlier JSON.
