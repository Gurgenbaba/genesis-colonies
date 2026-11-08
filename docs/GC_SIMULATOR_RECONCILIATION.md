# Simulator reconciliation: why the control says 887 days and the journey 325

> Measurement only. No game code, balance value, formula, migration or save game is changed. The analysis lives in `scripts/simulator_reconciliation.py` (tests: `tests/test_simulator_reconciliation.py`); every table below is regenerated into `docs/GC_SIMULATOR_RECONCILIATION_REPORT.md`.

## 1. Result in one paragraph

There is **no bug in either simulator**. The record-mine control (`scripts/sim_ascension_breakthroughs.py`) and the journey player (`scripts/player_journey_sim.py`, `never` arm) call the same canonical owners for prices, production curve and queue floor. The control simply prices a different world: **no research modifier, one mine, one currency**. Adding the journey's assumptions to the control one at a time (a ladder) moves it from **887 days to 325–330 days** for the metal mine from L200 to L300, against **324–326 measured** in the journey (deviation +0.2 % … +1.3 %). The same ladder lands within −1.3 % … −4.3 % of the journey for L100 → L200. **One assumption explains more than the whole net gap** (-625 days against -561 net): the control uses neutral production modifiers, the journey player has mining tech 69-71 and drone tech 3 when the metal mine reaches L200, which multiplies metal output by **3.38-3.45** (slot 1.04 x research 3.25-3.32). The other assumptions (second currency, crystal-mine upgrades, other spending, construction time) add back about +78 days.

The "289 days" quoted in the Ascension report was a different quantity: the pace of the **deepest** mine (usually the crystal mine, which leads the metal mine by 39–45 days at L300). The metal mine, which is what the control models, needs **324–326 days**.

## 2. What differs, and what does not

| Dimension | Record-mine control | Journey player (`never`) | Verified equal? |
|---|---|---|---|
| Upgrade prices | `power_upgrade_cost(key, target level)` | `get_upgrade_cost(key, current level)` | **yes**, same table, offset by one level (`price(k, L) == power_upgrade_cost(k, L+1)` is a test) |
| Production curve | `production_formula` UNI1 curve (pivot 120, tail power 3) | same, through `EffectResolver` | yes (rates equal the resolver to 1e-9) |
| Construction floor | `building_progress_floor_seconds` (10-30 s at L200-L300) | real build time 15.8 h (L200) ... 27.4 h (L300) with Nanofactory 3 | **no** (modelled in rung R6) |
| Start resources | 0 stock, L200 on day 0 | 150k / 100k / 25k at day 0, stock on hand when L200 arrives | start resources equal the fresh-account simulator; stock at the window start is worth about 1 day |
| Production modifiers | all 1.0 | slot x temperature x mining / drone / crystal tech (every other modifier is 1.0 in the sandbox) | **no**, this is the 3.4x |
| Research state | none | mining tech 47 (L100) ... 71 (L200+), growing through the window | **no** |
| Production sources | the mine itself | metal mine + crystal mine (+ standard output) | **no** |
| Currencies | one: price paid in metal + crystal, from metal output only | two, no Trader (crystal surplus is wasted), or Trader | **no** |
| Other spending | none | research, solar, storage, nexus: 3-4 % of production at L200+, 8 % below | **no** |
| Depots | unlimited | canonical storage capacity | no (does not bind, see R5) |

## 3. The ladder (metal mine, L200 to L300, days)

Each rung adds one assumption of the journey and keeps the previous ones. Rates come from `production_formula` with the journey's own research timeline, prices from `get_upgrade_cost`, construction time from `EffectResolver.get_build_time_seconds`. "Measured" shares (rungs R4) are read from the journey's ledger, so R4 onwards is a *decomposition*, not an independent forecast; R0-R3 are independent of the journey's results except for the order in which it bought research and crystal-mine levels.

| Rung | Assumption added | casual | active | optimizer |
|---|---|---:|---:|---:|
| R0 | control as published (neutral modifiers, one mine, one currency) | 887 | 887 | 887 |
| R1 | + canonical modifiers on the day the window starts (mining tech 69-71, drone tech 3, slot 1.04) | 257 | 262 | 262 |
| R2 | + research continues exactly as the journey bought it | 247 | 251 | 251 |
| R3 | + second currency; crystal mine upgraded alongside in the journey's order; no Trader | 309 | 311 | 311 |
| R4 | + non-mine spending as the journey's measured share of production | 319 | 321 | 322 |
| R5 | + depots (canonical storage capacity of the journey's storage buildings and tech) | 319 | 321 | 322 |
| R6 | + construction time (canonical build time, serial queue shared by both mines) | 325 | 328 | 330 |
| R6s | + stock on hand when the window began | 324 | 327 | 329 |
| **J** | **journey as measured** | **324** | **325** | **326** |

Reading it:

* **R0 → R1 is the whole story** (-625...-630 days): at the same L200 mine the journey player produces 11.2-11.4 B metal per hour, the control 3.31 B.
* The remaining rungs cost about +78 days together (second currency with the crystal mine upgraded alongside +60, other spending +10, construction latency +6...8) and land on the measured value. The order of rungs is a choice; the steps are not additive causes.
* **Depots do not bind** (R5 adds 0 days). The 15 % of production "lost to full depots" in the ledger is surplus crystal that was never the limiting resource.
* The three styles need the same number of days from L200 to L300 (324-326): the climb is resource-bound, the styles differ before L200 (L200 at day 356 / 372 / 419).

**L100 → L200** (control 649 days): R1 235-244, R2 210-213, R3 246-249, R4 267-268, R5 268, R6 **278-279**, measured **282-290** (casual 290, active 284, optimizer 282). The model is 1.3 % (optimizer) to 4.2 % (casual) faster than the journey; the rest is what the ladder does not model (nexus-cap waits below L200, energy ratio, the casual player's action windows).

## 4. Who gets the production inside the window

| Window | Metal mine | Crystal mine | Other (research, solar, storage, nexus) | Lost to full depots |
|---|---:|---:|---:|---:|
| L200 → L300 | 52 % | 44-45 % | 3-4 % | 15 % |
| L100 → L200 | 49-50 % | 41-42 % | 8 % | 8-10 % |

The policy spends almost as much on the crystal mine as on the metal mine although crystal is only a quarter of the metal mine's price. That is a *policy* property (payback ranking), not a simulator error; it is why the deepest mine leads the metal mine, and why the Trader helps.

## 5. Trader and the control's silent assumption

The control pays a metal + crystal price from metal output alone, i.e. it silently treats crystal and metal as perfectly fungible 1:1. The canonical Trader gives crystal → metal at 1:1 (metal → crystal 1.5:1) with a minimum, a score guard and a daily limit. The pooled-currency rungs are therefore an **upper bound** of the Trader: they finish 2 % (optimizer) to 8.5 % (casual) before the journey that really uses the Trader (L200 → L300: 314 / 310 / 296 days with Trader vs 324 / 325 / 326 without; pooled model 289 / 289 / 290).

## 6. The control's published levels are not ceilings

`docs/MINE_EVOLUTION.md`, `docs/GC_LONG_HORIZON_ENDGAME_AUDIT.md` and `docs/GC_TRAIT_R3_PLAYER_JOURNEY_GATE.md` call the control's levels (L237 / L273 after 6 / 12 months for one mature world) an upper bound. They are an upper bound for the *funding topology* (everything pooled into one mine, no side spending) but a **lower** bound for the modifier stack. Re-priced with the research the journey bought, from the same L200 start on day 0 (R2: one mine, one currency, no other spending):

| | 6 months after L200 | 12 months after L200 |
|---|---:|---:|
| Control (baseline q3) | L223 | L245 |
| Same question with the journey's research (R2) | L275-276 | L337-339 |

So the documented 6 / 12-month levels (including the 11-world pooled L508 / L705, which this reconciliation does not re-price) should be read as "neutral-modifier control", not as ceilings. The older documents are not edited here.

## 7. Early game: start resources and the first week

`scripts/fresh_account_progression_sim.py` (a third, greedy always-attentive builder) uses the same start resources (150,000 / 100,000 / 25,000), the same speed settings (production 1.0, build 1.1, research 0.85) and the same resolver. Against it:

| Day 7 | Metal mine | Metal / h | Crystal / h |
|---|---:|---:|---:|
| fresh-account sim | L27 | 43.5 k | 29.0 k |
| journey optimizer | L28 | 68.5 k | 48.9 k |
| journey active / casual | L14 / L4 | 29.8 k / 19.9 k | 20.2 k / 13.7 k |

The optimizer matches the always-attentive builder on depth and is ahead on income (mining tech, which the fresh simulator never buys). The fresh simulator stops progressing after week one (still L27 on day 30), so it cannot anchor anything later.

## 8. What can be quoted and what cannot

| Statement | Status |
|---|---|
| Metal mine L200 → L300 takes **about 325 days** (324-326) for a policy-v2 player, L100 → L200 about **285 days** (282-290) | **Released** as a journey-model estimate. Reproduced from the canonical owners to +1.3 % / -4.3 %; the policy (research order, crystal-mine share) is an input, not a result. |
| Deepest mine L200 → L300 about **290 days** | Released, same basis (crystal mine leads by 39-45 days). Use "metal mine" or "deepest mine" explicitly. |
| Calendar day of L200 (day 356-419) | **Released with a caveat**: L100 → L200 is reproduced; days 1-7 are anchored by the fresh-account simulator; days 8-74/129 (L0 → L100) are the journey's own accounting only. |
| "887 days from L200 to L300" | **Withdrawn as a progression time.** It is the neutral-modifier, one-mine, one-currency control. |
| The control's 6 / 12-month levels as ceilings | **Withdrawn** (section 6). |
| Ascension is a net loss within 24 months (report #559) | **Unaffected.** Those runs live entirely inside the journey simulator (canonical modifiers, two currencies, real build times); only the control cross-check was off. |
| Mine cap / PL15 gate | No change proposed. |

## 9. Limits

* **A decomposition, not a second opinion on policy.** The ladder uses the journey's decisions (research order, crystal-mine order, share of non-mine spending) as inputs. It validates the simulator's *accounting* (production, prices, storage, queue), not whether a human would play like policy v2.
* **Residual 1-4 %** (L100 → L200): nexus-cap waits, energy ratio, action windows; not modelled in the ladder.
* **Hidden dependency found and fixed in the harness:** `player_journey_sim._upgrade_cost` is a process-wide `lru_cache` keyed by (building, level) while the price table depends on the active endgame curve (L250 metal mine: 3.2e14 in the legacy curve, 1.5e12 in UNI1). One price lookup outside the curve poisons every later run in the same process (the control then looked like 5,445 days in one test). The reconciliation clears the cache around its runs (`uni1_curve()`, covered by a test). The published tables were not affected, the simulator itself is unchanged.
* S1 (one planet) only; multi-planet pooling, outposts and transport are not part of this reconciliation.
* The outpost-XP defect (#556) does not touch an S1 window; the baseline caveat of the stack stays.

## 10. Reproduce

```bash
python scripts/simulator_reconciliation.py --out-json artifacts/reconciliation/latest.json --out-md docs/GC_SIMULATOR_RECONCILIATION_REPORT.md
python -m pytest tests/test_simulator_reconciliation.py -q
```

About one minute (six journeys of 900 days plus the early-game anchor).
