# Ascension r4: robustness, audit and the five pre-release conditions

> Measurement and code reading only. No game code, balance value, formula, migration or save game is changed. Candidates are **counterfactual rule sets applied as a sandbox patch** of the canonical Nodebuster owner for one simulated run (and restored afterwards); nothing here is a proposal. Analysis: `scripts/ascension_r4_checks.py`, tests: `tests/test_ascension_r4_checks.py`, generated tables: `docs/GC_ASCENSION_R4_CHECKS_REPORT.md`. Builds on `docs/GC_ASCENSION_MILESTONES.md`.

## 1. Question and result in one table

`r4` ("Record Milestones": awakening +7 %, keep 85 % of the record, two record tiers, AP only for record progress) met all four acceptance checks of the milestone study on one planet - on the boundary of each (346 of 365 days, gain 0.022 of 0.02, best response 1.249 of 1.25). Five conditions were set before any live decision.

| # | Condition | Result |
|---|---|---|
| 1 | Robustness (seeds, strategies, casual asymmetry) | **Not robust.** The world seed has no effect on the simulated economy. Of 19 parameter points around r4 only r4 passes (1 of 19); r4 fails K4 under the older player strategy (1.277); under PL10 and PL12 the first reset still pays back (metal-only start 325-357 days) but the second reset no longer clears its limit (+0.013 / +0.002 vs 0.02). |
| 2 | Ranking, records, achievements | **No bypass found.** Ranking counts `max(current level, best depth)`; records count the current level (more stable than today); there is no achievement on mine levels. One UI/rule gap: the Ascend button would stay enabled after a restart at or above L200. |
| 3 | AP fairness | **Holds, tested through the real owner.** Same depth again earns 0 AP; existing AP, skills and records are untouched; record-based AP are never above today's award and sum to a function of the record. |
| 4 | Farming stress | **No dominant strategy.** Button-masher, micro ladders, crystal-only and very late resets all end 0.03-1.07 below the best sensible policy. |
| 5 | Casual 507 vs 329 days | **Explained by the crystal mines.** A crystal reset is worth about half a metal reset but costs the same: crystal-only pays back in 712 days, metal-only in 329, both in 507. |

## 2. Condition 1 - robustness of r4

### 2.1 World seeds: no effect on the economy

The simulator pins the homeworld's coordinates and DNA with the world seed. Probes with 8 seeds on one planet and 6 eligible-DNA seeds on 11 planets (730 days, active style) gave **the identical empire income to the last unit** (149,391,117,762 and 1,003,468,138,677 per hour) and identical mine depth and 11th-world day. The mine economy, the colony pipeline and therefore every number of the reward studies do not depend on the seed; DNA only matters for specialisations and mandates. Pinned by two tests (`test_world_seed_does_not_change_the_economy`). Consequence: planet-to-planet variation (world-type multipliers, trait effects) is **not modelled at all** (listed in the simulator's NOT_MODELLED), so "several world seeds" cannot be tested with this tool; it would need those mechanics in the sandbox.

### 2.2 The neighbourhood of r4: only r4 passes

19 parameter points (S1, 3 styles, 7 arms each): awakening 6-8 % x tier output 2-3 %, kept share 80 / 90 %, rebuild cost x0.25 / x0.35.

| Limits | Passing |
|---|---|
| base (K2 gain >= 0.02, K4 <= 1.25) | **1 of 19** (r4) |
| K2 gain >= 0.01 | 3 of 19 (r4, g700_200, gc25) |
| K2 gain >= 0.00 | 4 of 19 (+ g750_200) |
| K4 <= 1.30 | 5 of 19 (r4, r1, g750_300, g800_300, gk90) |
| K2 >= 0.00 and K4 <= 1.30 | 9 of 19 |

r4's margins: 19 days to the payback limit, **+0.002** to the second-reset limit, **+0.001** to the best-response limit. Every single step away fails one check: less awakening (6-6.5 %) misses the payback (376-406 days), more awakening or more tier output breaks K4 (1.26-1.30), less tier output misses K2, keeping 80 % misses the payback (466 days), 90 % breaks K4 (1.270), a cost of x0.35 misses the payback by 1 day. **r4 is the one grid point that happens to fit through; there is no robust window under these limits.** The conflict is structural: the same reward is worth far more to the casual style (second reset +0.05) than to the optimizer (-0.006), K4 caps the casual style's best response, K2 asks the weaker styles to profit from repeating. If the limit for the second reset is relaxed to "does not lose" a band appears (awakening 7-7.5 %, tier output 2 %: margins +19..+44 days and +0.013..+0.024 to K4), but then the benefit of the second reset is +0.006..+0.012 of cumulative production - roughly one to three weeks of production over six years, hardly "visible".

### 2.3 Player strategy: a less efficient player gets more out of it

pj-policy/1 (goal list + patience) plays a weaker economy: its `never` income is 1.6x lower at 48 months and its first reset comes later (day 505-594 vs 349-409). Same candidates, S1:

| | K1 slowest (days) | K2 gain 2nd / 3rd | K4 best response | Cum. 48 / 72 mo (`O200`) |
|---|---:|---|---:|---|
| `r4`, policy v2 (base) | 346 | +0.02 / +0.01 | 1.249 | 1.12 / 1.15 |
| `r4`, policy v1 | 180 | +0.05 / +0.04 | **1.277** | 1.15 / 1.17 |
| `rank1_fast`, policy v2 (base) | 631 | -0.09 / -0.19 | 1.211 | 1.12 / 1.17 |
| `rank1_fast`, policy v1 | 365 | -0.04 / -0.06 | 1.245 | 1.16 / 1.22 |

The weaker the player's own build order, the more a cheap rebuild and a permanent bonus are worth: **K4 fails for r4 under policy v1** (1.277), and the payback halves. A candidate calibrated on the efficient player is too strong for the typical one - the reverse of what a fairness margin should do.

### 2.4 Colonisation gate

S11, up to 11 planets, the three gates on the same economy (PL15 is the base run of the milestone study; PL10 and PL12 are sandbox levers that lower the colony-maturity gate for the run).

| Gate | 11th world, `never` (day; casual / active / optimizer) | `r4` `O200` slowest payback | `r4` `P200` slowest payback | `r4` gain 2nd / 3rd reset | `r4` best response | `rank1_fast` `O200` slowest |
|---|---|---:|---:|---|---:|---:|
| PL10 | 424 / 270 / 230 | 470 | 325 | +0.013 / +0.001 | 1.18 | 740 |
| PL12 | 504 / 348 / 312 | 460 | 357 | +0.002 / +0.007 | 1.17 | 755 |
| PL15 | 642 / 481 / 442 | 507 | 329 | +0.021 / +0.014 | 1.20 | 802 |

* **The first-reset economics are stable across the gates.** With the metal-only start the slowest style pays back in 325-357 days under every gate (`K1 best start` ok three times, the PL12 margin is 8 days); the whole-empire casual campaign needs 460-507 days; `rank1_fast` 740-802.
* **The repeat value is not.** The second reset adds +0.021 under PL15 but +0.002 under PL12 and +0.013 under PL10, the third +0.014 / +0.007 / +0.001: **K2 (second reset >= 0.02) fails under PL10 and PL12.** With a faster colony pipeline the economy is larger and growing when the second reset falls due, and it competes with colony growth for the same resources. The gain is in the noise of 0 to +0.02, not a stable property.
* **Side result for the PL10 / PL12 / PL15 step** (`never`, same simulator, same policy): PL12 brings the 11th world forward by about 130-140 days (PL10: about 210-220), and the income at 48 months is +6..+10 % over PL15 (PL10: +10..+15 %), at 72 months +2..+6 % (PL10 +5..+8 %), casual > active > optimizer in every case. PL12 delivers roughly 60-70 % of the PL10 effect.

## 3. Condition 2 - ranking, records and achievements (code audit)

| System | What it reads | Effect of a restart at 85-91 % of the record |
|---|---|---|
| Ranking score (`game/ranking_core.py`, `score_level`) | `max(current level, best_depth)` per mine, priced by cumulative upgrade cost | **Reset-neutral by design**, unchanged. `best_depth` only rises with real depth, so repeated resets at the same depth add nothing; a restart level cannot lower or raise the score (test). |
| Universe records (`game/records.py`, `_top_building_record`) | `MAX(planet_buildings.<building>)` - the **current** level, not the lifetime record | A reset lowers the holder's current level: today to at most L156, with r4 to 85-91 % of the record. Records become *more* stable, no bypass. Open question for the owner: should a record use `best_depth`? |
| Achievements | nothing for mine levels (the only `achievement` in `game/` is `has_apex_achievement` for the planet specialisation) | none |
| Build caps (`game/buildings.py`) | under Nodebuster mines are uncapped (`QUEUE_SAFETY_SENTINEL`) | none |
| Skill prerequisites (`nodebuster.SKILL_CATALOG`) | `requires_best_depth` 300 / 400 / 500 for the breakthrough skills | compatible: `best_depth` rises only through real records, as before |
| Rebuild surge window (`queue_engine`, `production_formula`) | `best_depth` (+50 with Breakthrough Window) | the surge window covers record - restart levels, so a restart at 85-91 % shortens it from about 144 levels (record 300, canonical restart at most 156) to 27-45 levels (a smaller Legacy Reconstruction benefit; not modelled) |
| Ascend button (`nodebuster.panel_fields`, `templates/buildings.html`) | `evolution_can_evolve = level >= 200` | **gap:** with a restart at or above L200 the button stays enabled after a reset. A press then earns nothing under r4 but sets the level to 85-91 % of the record - a misclick at 290 with record 300 costs 17 levels. The design rule below would make the rule itself require a new record. |
| Planet evolution, research-lab and shipyard Ascension, Stellar Forge | their own tables | not touched |

## 4. Condition 3 - AP fairness and compatibility

Tested through the real owner in a sandbox (`test_existing_ap_and_skills_survive_a_switch_to_record_based_ap_through_the_real_owner`, `test_record_based_ap_are_never_more_generous_than_canonical_and_sum_to_the_record`):

* **No re-earning at the same depth:** resets at L200, L250, L250, L200, L300, L260 award 1, 2, 0, 0, 3, 0 AP.
* **Existing state is compatible:** a mine that ascended three times at L200 under today's rules (3 AP earned, 1 skill bought) keeps `points_earned`, `points_unspent`, its skill ranks and its `best_depth` when the record rule takes over; the next reset at the same depth gives 0 AP, at L250 2 AP. No migration is needed because the rule only reads `best_depth`, which is already stored.
* **Never more generous than today:** for every pair (level, previous record) up to L640 the record-based award is between 0 and today's award; over any sequence of resets the total equals `points_for_depth(highest level)`, which is below the sum of today's per-reset awards.
* **Open point, not a defect:** a player who already farmed AP under today's rules holds more AP than `points_for_depth(best_depth)` and keeps them (no claw-back). A cut-off date or an AP credit (new points only once the record's value exceeds what was already earned) would be a decision for the owner.

## 5. Condition 4 - farming stress

The stress policies are harsher than the four resets of the earlier studies. Cumulative production vs `never` at 72 months, median (range); *gap* = minus the best sensible policy of the style.

| Policy (r4) | S1 | S11 |
|---|---|---|
| `A200` button-masher: resets whenever a mine is at or above L200, once a week per mine, never stops building | 0.02 (0.01-0.02), 142 resets, **2 AP** | 0.02 (0.01-0.02), 1,373 resets, 22 AP |
| `L200+1` every +1 level over the record | 0.12 (0.06-0.16), 250 resets, 15 AP | not run |
| `L200+10` every +10 levels | 0.41 (0.28-0.66), 60 resets, 30 AP | 0.39 (0.25-0.48), 618 resets, 302 AP |
| `C200` crystal mines only | 1.05 (1.02-1.05) | 1.03 (1.02-1.04) |
| `O350` / `O400` one very late reset | 1.17 (0.98-1.21) / 1.11 (0.96-1.17) | not run |

* **Delayed ascending is not an exploit:** `O350` 1.17 and `O400` 1.11 stay below the first-reset policies at L250 / L300 (1.21 / 1.25 for the casual style).
* **Selective resets** (metal only, crystal only, homeworld only, one mine) never exceed 1.09 for r4 (S1 and S11).
* **AP cannot be farmed:** the button-masher with 142 resets earns 2 AP (the first reset of each mine); the 250-reset micro ladder 15 AP (`points_for_depth` of its record). The same policies under `rank1_fast` (canonical AP per reset) earn 67-151 AP while destroying the economy (0.01-0.07 of `never`).
* The S11 button-masher issues 1,373 resets in six years; the weekly cooldown is part of the policy, the owner has none. An engineering limit (cooldown or "ascend only above the record") would still be sensible to keep the database and the event log small.

## 6. Condition 5 - why the casual whole-empire reset takes 507 days and the metal-only start 329

S11, r4, 48 months; casual against active (full tables in the generated report).

| | Casual `O200` | Casual `P200` metal | Casual `C200` crystal | Active `O200` / `P200` / `C200` |
|---|---:|---:|---:|---:|
| Payback (days) | 507 | **329** | 712 | 343 / 259 / 423 |
| Cum. production 24 / 48 mo | 0.93 / 1.07 | 1.00 / 1.07 | 0.95 / 1.01 | 1.00 / 1.11, 1.03 / 1.08, 0.99 / 1.03 |
| Resets after 12 / 24 months | 0 / 14 | 0 / 7 | 0 / 7 | 3 / 18, 2 / 9, 2 / 9 |
| Reset campaign length (days) | 606 | 554 | 588 | 416 / 398 / 401 |

Measured:

* **A crystal reset is worth about half a metal reset and costs the same.** The cliff of the planet is 0.67 after a metal reset and 0.79 after a crystal reset, both mines rebuild in about the same number of days (casual 15-16, active 11-13), but the +7 % bonus applies to the mine's own output and crystal is roughly a third of the income. Crystal-only pays back 2.2x slower than metal-only (712 vs 329 days), and the crystal resets drag the casual empire by 7 percentage points at 24 months (0.93 vs 1.00) and only reach break-even at 48 months (1.07 both). For the active style the crystal resets still add +0.03 at 48 months (1.11 vs 1.08).
* **The casual style starts later and works slower:** first reset on day 398 (active 342), 0 resets in the first year, a campaign of 606 days (416), rebuilds 3-4 days longer.
* **It is not queue saturation:** the casual planets' build queues are busy 35-37 % of the time with or without resets; the spend on mines and research stays within -6..+8 % of `never` (mines 0.94, research 0.97 at 24 months for `O200`).

Not measured: why a casual rebuild takes 3-4 days longer (check-in cadence is the obvious candidate, the diagnostics do not separate it). Practical consequence: the campaign is cheapest when it starts with the metal mines (`K1 best start`: 329 days for every style); a rule or UI that offers the crystal reset *later* would remove the drag.

## 7. The design rule and what it implies for Ascension V3

> A new record depth rewards progress - not pressing the reset button.

Everything measured here is consistent with it, and the audit shows where the rule is only implicit: AP and tiers follow the record, but the **eligibility** to ascend (`level >= 200`) does not. Making eligibility record-bound ("first Ascension at L200, every further one only above the record") would turn the farm from "unprofitable" into "impossible", remove the misclick penalty, keep the event log small and make the AP and tier rules a consequence instead of a patch. Decisions that remain with the owner: record vs current level in the universe records; AP credit for legacy farmers; whether the restart-below-L200 invariant may go (r4's repeat value depends on it: with the canonical ceiling the second reset is +0.02 at best and the third -0.08); how to treat the narrow window (section 2.2) - relax K2, accept a casual best response up to 1.30, or find a mechanism whose reward does not scale with the weakness of the player's own economy.

## 8. Limits

* The simulator has no world-type multipliers or trait effects, so the seed check proves independence of the *model*, not of the game.
* Policies are fixed; thresholds are this analysis' operationalisation; one homeworld seed in S11; the baseline includes the outpost-XP defect (#556 not applied).
* The audit is a code reading of this checkout (`ranking_core`, `records`, `buildings`, `nodebuster`, `queue_engine`, templates); systems that live outside it (external clients, admin tools, live data) were not inspected.
* The casual explanation covers the economics, not the 3-4 day longer rebuild.

## 9. Harness changes in this step (simulator tooling, no game change)

* Policies `A<n>` (button-masher with a weekly cooldown), `C<n>` (crystal mines only); lever `colony_gate_pl12`.
* `scripts/ascension_r4_checks.py` with five suites (grid, stress, strategy, gates, casual), threshold sweep, margins and a markdown report; the milestone runner takes strategy, gate lever, variant tag and diagnostics (spend by category, queue occupancy, colony pipeline).
* Tests: 17 in `tests/test_ascension_r4_checks.py` (stress policies, AP compatibility through the real owner, rank score, seed independence, suites, analysis).

## 10. Reproduce

```bash
for s in casual grid stress strategy gates; do python scripts/ascension_r4_checks.py --suite $s --workers 11 --out-json artifacts/ascension_r4/$s.json; done
python scripts/ascension_r4_checks.py --report docs/GC_ASCENSION_R4_CHECKS_REPORT.md
python -m pytest tests/test_ascension_r4_checks.py -q
```

About 6 minutes (casual), 8 (grid), 16 (stress), 4 (strategy) and 33 (gates) on 11 cores.
