# Colony gate PL10 / PL12 / PL15 - final comparison

> Measurement only. No game code, balance value, formula, migration or save game is changed; the gate levels are the existing sandbox levers (`colony_gate_pl10`, `colony_gate_pl12`), which patch `COLONY_MATURITY_REQUIRED_LEVEL` for one simulated run and restore it. Analysis: `scripts/colony_gate_final.py`, tests: `tests/test_colony_gate_final.py`, generated tables: `docs/GC_COLONY_GATE_FINAL_REPORT.md`, telemetry queries: `scripts/expedition_xp_telemetry.py`. Builds on `docs/GC_COLONY_GATE_PL10_VS_PL15.md`.

## 1. What was open, and what this adds

The PL10 vs PL15 study listed four gaps: the middle option PL12, expedition XP, the outpost-XP fix (#556), and several DNA seeds. This closes them as far as the simulator can:

* **PL12** is simulated next to PL10 and PL15 (S11, three player styles, 24 and 48 months).
* **Expedition XP** is a dose-response of 0 / 3 / 6 / 15 expeditions per day launched from the colony that holds the chain (15 XP each, +75 per 10, no daily cap, as `game/activity_xp.py`). While preparing this a simulator inconsistency was fixed: the focus colony was judged against the constant 15, so under PL10 / PL12 the expedition XP would have gone to the wrong colony. It now follows the live gate (identical at PL15, so no earlier result changes; a test pins it).
* **#556** is re-run: the same scenarios in a scratch checkout that carries the two #556 commits (this branch does not contain them).
* **DNA / world seeds:** answered earlier (`docs/GC_ASCENSION_R4_CHECKS.md`): the seed does not change the simulated economy (identical to the last unit), so more seeds would repeat one number. Planet-to-planet variation is not modelled.

72 scenarios (54 without the fix, 18 with it), arm `never`, policy v2, UNI1 curve, one homeworld seed with eligible DNA; all simulator invariants hold.

## 2. Result in short

1. **The baseline reproduces the earlier study exactly** (11th world casual 642 -> 424, active 481 -> 270, optimizer 442 -> 230 for PL15 -> PL10). **PL12 sits at 61-63 % of the PL10 date effect:** 11th world on day 504 / 348 / 312 (casual / active / optimizer), that is 131-138 days earlier than PL15 (PL10: 212-218).
2. **The economic lead is a head start, and PL12 delivers about 60 % of it.** `never`, income against PL15 at 12 / 24 / 48 months: PL12 +14 / +22 / +10 % (casual), +18 / +20 / +7 % (active), +17 / +17 / +6 % (optimizer); PL10 +32 / +35 / +15 %, +42 / +34 / +12 %, +42 / +29 / +10 %. Cumulative production at 24 months: PL12 +19..21 %, PL10 +36..41 % (PL12 = 52-58 % of PL10); at 48 months PL12 +9..15 %, PL10 +16..22 % (59-68 %). In days, PL12 is 30-35 days ahead at 24 months and 30-50 at 48 months (PL10 55-65 and 55-70).
3. **Expedition XP is a bigger lever than the gate.** With the expedition XP landing on the colony under development, the PL15 chain alone speeds up by more than a gate change does (11th world, PL15, casual / active / optimizer: 642 / 481 / 442 days with none, 449 / 353 / 323 at 3 per day, 374 / 293 / 257 at 6, 190 / 175 / 146 at 15). Three expeditions per day already put casual PL15 (449) next to casual PL10 without expeditions (424). The days a lower gate buys shrink accordingly (PL10 vs PL15, casual: 218 -> 189 -> 151 -> 74 days; PL12: 138 -> 131 -> 75 -> 51), and at 6 per day the 48-month production lead of PL12 is only +7 / +5 / +4 %.
4. **Fairness is neutral for the gate itself, and the expedition habit is far larger than the gate.** With the same rate for every style the casual / optimizer ratios hardly move (income at 24 months 0.54 / 0.57 / 0.57, production 0.48 / 0.49 / 0.48 for PL15 / PL12 / PL10). If the styles differ in the habit (casual 3 per day, optimizer 15), the optimizer finishes the chain on day 146 and the casual player on day 449 under PL15 (date ratio 3.07; PL12 2.86; PL10 2.76) - a gap no gate level closes - while the lower gates narrow the income gap (casual / optimizer income at 24 months 0.50 -> 0.58 -> 0.64).
5. **#556 is within the simulator's noise, with a small structural delay.** Over all 18 style / gate / rate pairs the fix moves the 4th world by +1.2 days on average (range -1 ... +4, later in 13 of 18), the 11th world by +2.5 days (range -10 ... +9, later in 14 of 18) and the 24-month production by -0.8 % (range -5.8 % ... +6.8 %). There is no gate-specific pattern (PL10 / PL12 shifts are the size of the PL15 ones). The mechanism points the same way as the sign of the early shifts: a new colony cannot level before its three establishment buildings exist. The spread beyond that is treated as noise; it was not measured separately because the seed does not vary the run.
6. **The gate wait explains the PL15 chain, expeditions remove most of it.** Share of the first 24 months spent at the maturity gate under PL15: 58-83 % without expeditions, 33-57 % at 3-6 per day, 18-23 % at 15 per day.

## 3. What follows for PL12

* PL12 is a coherent **middle option**: about 4-4.5 months earlier to a complete empire for players who do not take expedition XP onto their colonies, about 60 % of what PL10 does, with a long-run economy effect of +6..10 % income at 48 months (+2..5 % when expeditions already feed the colonies).
* The simulator **cannot choose the gate**: it prices a 4-7 month pull-forward of the complete empire with a small long-run economic effect. Whether that pull-forward is wanted is a pacing / retention decision.
* The decision depends on one number the simulator does not have: **how much colony XP comes from expeditions launched from the colony today.** That is already in `activity_xp_log` (expedition XP is granted to the *origin planet* of the movement). If it is large, the gate is mostly moot and PL15 can stay; if it is rare, PL12 is the reasonable candidate and the expedition rule becomes a separate question (C3 in `docs/GC_RELEASE_PLAN.md`). Read-only queries: `python scripts/expedition_xp_telemetry.py --print-sql`.
* **PL12 is not release-ready.** Still missing: the telemetry above; a staged gate (for example PL10 for colonies 2-5, PL15 beyond) that has not been simulated; real ship, fuel and fleet-slot limits for the expedition rates.

## 4. Limits

* **The expedition runs are an upper bound.** All expedition XP lands on the colony that holds the chain; no ships, fuel, fleet slots, travel, loot or stay time are modelled; the rate is the same for every style (and 15 per day may be out of reach). Real players are somewhere between the 0 per day rows and these rows. The 0 per day rows are the lower bound the earlier study used.
* One homeworld seed, mid climate, three fixed player styles, policy v2, no transport between planets. The model has no planet-to-planet variation and no trait / world-type multipliers.
* Online windows (casual 09:00 and 21:00, active 07 / 12 / 17 / 22, optimizer always) are assumptions.
* The simulator's own scan-stop rule still stops DNA scanning of colonies at planet level 15 (changing it moved the casual 11th world by -0.5 day in the earlier study; not applied, so the PL10 / PL12 rows are very slightly conservative).
* #556 was applied by cherry-picking its two commits in a scratch checkout; the rest of the code is identical. The noise was not measured on its own.
* The lead in days uses a series sampled every 5 days.

## 5. Reproduce

```bash
python scripts/colony_gate_final.py --suite base --workers 8 --out-json artifacts/colony_gate_final/base.json
# in a scratch checkout that carries the two #556 commits:
python scripts/colony_gate_final.py --suite fix --workers 4 --out-json artifacts/colony_gate_final/fix.json
python scripts/colony_gate_final.py --report docs/GC_COLONY_GATE_FINAL_REPORT.md
python -m pytest tests/test_colony_gate_final.py tests/test_expedition_xp_telemetry.py -q
```

About 20 minutes on twelve cores for the base suite (the 48-month runs dominate).
