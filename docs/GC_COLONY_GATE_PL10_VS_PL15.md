# Colony gate PL10 vs PL15 under the corrected mine progression

> Measurement only. No game code, balance value, formula, migration or save game is changed; the mine cap and the level-15 colonisation gate are **not** touched. The gate difference is the existing sandbox lever `colony_gate_pl10` (it patches `COLONY_MATURITY_REQUIRED_LEVEL` for the duration of a simulated run and restores it). Analysis: `scripts/colony_gate_analysis.py`, tests: `tests/test_colony_gate_analysis.py`, generated tables: `docs/GC_COLONY_GATE_PL10_VS_PL15_REPORT.md`.

## 1. Question and setup

Colony n+1 can only be launched once every existing colony has reached planet level 15. The progression report measured a PL10 gate in the *capped* model (mines stopped at L200), the Ascension report showed that under `nodebuster-v1` mines are not capped. This repeats the comparison in the corrected model, after the two simulators were reconciled (`docs/GC_SIMULATOR_RECONCILIATION.md`).

* S11 journeys (up to 11 planets), casual / active / optimizer, policy v2, UNI1 endgame curve, homeworld seed with eligible DNA, 730 days (arm `never` also 1,460 days).
* Gate **PL15** (the game) against **PL10**. Arms: `never` (keep building, canonical queue rules), `T200` (ascend every mine at L200), and `legacy` (the capped model of the progression report) as a correction table.
* 24 runs; all simulator invariants hold.

## 2. Result in short

1. **PL10 moves the 11th world forward by about 210 days for every style** (casual 642 → 424, active 481 → 270, optimizer 442 → 230). The chain is the largest single wait of the first two years: at PL15 the empire spends 83 % (casual), 62 % (active), 58 % (optimizer) of the 24 months at the maturity gate; at PL10 53 / 33 / 29 %.
2. **The economic lead is real but is a head start, not a different endgame.** `never`, 24 months: income **+35 / +34 / +29 %**, cumulative production **+37 / +41 / +36 %** (casual / active / optimizer), equivalent to being **55-65 days ahead**. At 48 months the income lead has shrunk to **+15 / +12 / +10 %** (production +22 / +18 / +16 %), the lead in days is still 55-70, and the deepest mine is the same (L485-496 vs L484-495).
3. **Casual fairness is neutral to mildly positive.** PL10 helps the casual player by the same relative amount as everyone else (production +37 % vs +36 % for the optimizer), so the casual / optimizer ratios hardly move (income at 24 months 0.54 → 0.57, production 0.48 → 0.48). What changes is access: a casual player under PL10 has 11 worlds on day 424, **earlier than an optimizer under today's rules (day 442)**, and reaches 0.74 of that optimizer's income at 24 months (instead of 0.54).
4. **Late colonies do not stay stunted.** With PL10 the median world is *closer* to the best one (median / best at 24 months: casual 0.78 → 0.89, active 0.88 → 0.93, optimizer 0.91 → 0.94; shallowest metal mine L84 → L181, L193 → L261, L211 → L269), because every colony has more time.
5. **No new brake appears when the gate drops.** The homeworld slot gate stays at 2-3 % of the time and ark build / flight at ≤ 1 %; after the chain is complete the empire spends 42-69 % of the 24 months with "all colonies founded".
6. **Correction of the earlier number.** In the capped model PL10 gave income +30 / +2 / −1 % at 24 months (mean +10 %, matching the progression report's +11 %) because colonies could not add depth to an economy that stopped at L200. In the corrected model the same gate gives **+35 / +34 / +29 %**. The earlier statement should be read as "capped-model result".

## 3. Colony timeline (`never`)

| Style | Gate | 2nd | 4th | 6th | 8th | 11th world | Days per colony | Gate wait (24 mo) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| casual | PL15 → PL10 | 14 → 14 | 155 → 107 | 294 → 197 | 433 → 288 | **642 → 424** | 70 → 46 | 83 → 53 % |
| active | PL15 → PL10 | 10 → 10 | 115 → 68 | 220 → 127 | 323 → 184 | **481 → 270** | 52 → 29 | 62 → 33 % |
| optimizer | PL15 → PL10 | 7 → 7 | 104 → 58 | 198 → 107 | 294 → 157 | **442 → 230** | 48 → 25 | 58 → 29 % |

The first colony is not gated. The chain is bound by planet XP of the colony under development (DNA scans, building and research finishes), not by resources, which is why the gate costs the same ~210 days for every style. `T200` gives the same dates within ±5 days: Ascension does not interact with the chain.

## 4. Economic lead (`never`)

| Style | Checkpoint | Worlds PL15 / PL10 | Income change | Production change | Lead |
|---|---|---:|---:|---:|---:|
| casual | 12 mo | 7 / 9 | +32 % | +30 % | 15 d |
| casual | 24 mo | 11 / 11 | +35 % | +37 % | 55 d |
| casual | 48 mo | 11 / 11 | +15 % | +22 % | 70 d |
| active | 12 mo | 8 / 11 | +42 % | +37 % | 25 d |
| active | 24 mo | 11 / 11 | +34 % | +41 % | 65 d |
| active | 48 mo | 11 / 11 | +12 % | +18 % | 65 d |
| optimizer | 12 mo | 9 / 11 | +42 % | +38 % | 30 d |
| optimizer | 24 mo | 11 / 11 | +29 % | +36 % | 55 d |
| optimizer | 48 mo | 11 / 11 | +10 % | +16 % | 55 d |

Income = empire metal + crystal per hour; production = cumulative gross output; lead = days earlier PL10 reaches the income PL15 has at that checkpoint. The lead in days stays flat while the relative advantage decays, because growth slows (the best mine gains 1.4-2.6 % per level, one level per ~3 days).

**`T200`.** Ascension resets mines on its own cycle, so income on a single day is dominated by where each style is in its rebuild (−3 … +54 % at 24 months); the cumulative production is the robust measure: **+35 / +23 / +20 %** at 24 months. `T200` stays far below `never` in absolute terms (income 89-143 B vs 0.6-1.1 T at 24 months), as in the Ascension report.

## 5. Casual fairness in detail (`never`)

| Gate | 11th world casual / active / optimizer | Day ratio casual / optimizer | Income 12 mo ratio | Income 24 mo ratio | Production 24 mo ratio |
|---|---|---:|---:|---:|---:|
| PL15 | 642 / 481 / 442 | 1.45 | 0.36 | 0.54 | 0.48 |
| PL10 | 424 / 270 / 230 | 1.85 | 0.33 | 0.57 | 0.48 |

The day ratio grows because the same absolute gap (≈ 200 days) now sits on a shorter chain; in days the casual-to-optimizer gap is unchanged (200 → 194). The casual player's economic deficit (0.5×) is **not** caused by the gate: it comes from later and shallower colonies and slower research, and it is unchanged. That is the part the planned "reserve next purchase" feature addresses, not the gate.

## 6. What this does and does not say about "a progression brake"

* The serial PL15 chain is the dominant pacing element of the first 24 months in an 11-planet game: 58-83 % of the time is spent waiting for planet XP, independent of how rich the player is.
* Removing 5 levels of it buys a **~2-month head start** in the long run (+10-15 % income at 48 months), 7 months earlier to a complete empire, and +30-40 % production in the first two years. It does not change the shape of the endgame: depth keeps growing at the same pace afterwards (L330 at 24 months, L495 at 48 months in both).
* Whether "7 months more to a full empire" is too slow is a retention and feel question the simulator cannot answer; it shows that the long-run economy does not suffer much from PL15 and that PL15 is not a casual-specific penalty (the absolute gap is the same at PL10).
* Options this evidence would let us price next (none is proposed here, none changes a value): keep PL15; PL10; a staged gate (for example PL10 for colonies 2-5, PL15 beyond); or a faster XP source for the colony under development instead of a lower gate.

## 7. Release readiness

**PL10 is a serious candidate, not release-ready.** Missing before any decision (also PL12 as a middle option has not been simulated yet):

* real expedition XP (this analysis models none, so the chain may be faster than simulated at either gate);
* several homeworld / DNA seeds (one seed here);
* a re-run with the outpost-XP fix of #556 (not applied; noise under PL15, not measured under PL10).

## 8. Limits

* One homeworld seed (eligible DNA), mid climate, three fixed player styles, policy v2. S11 pools nothing between planets (no transport).
* XP model: DNA scans, building and research finishes. Expeditions, quests and other XP sources are not modelled (0 expeditions per day), so real players may chain faster than simulated at either gate.
* **Outpost-XP defect (#556) is not applied.** Under PL15 it moved the 11th world by −2 … +7 days (noise, Ascension report section 9); it was not re-measured under PL10.
* **Simulator-internal consistency:** the lever patches the canonical gate constant, but the simulator's own scan-stop rule still stops scanning colonies at 15. Making it stop at 10 changes the casual 11th world by −0.5 day and income by +0.4 %, active and optimizer by 0 (checked, not part of the committed tables).
* `T200` income on a single day depends on the rebuild phase; use the production columns.
* The "lead in days" uses a series sampled every 5 days.

## 9. Reproduce

```bash
python scripts/colony_gate_analysis.py --workers 10 --out-json artifacts/colony_gate/latest.json --out-md docs/GC_COLONY_GATE_PL10_VS_PL15_REPORT.md
python -m pytest tests/test_colony_gate_analysis.py -q
```

About eight minutes on ten cores (24 scenarios, the 48-month runs dominate).
