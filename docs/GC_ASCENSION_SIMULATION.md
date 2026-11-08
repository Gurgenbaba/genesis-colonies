# GC — Mine Ascension After L200: What Happens, and When It Pays

**Status:** measurement only. No game value, formula, save game, migration or deployment is touched; nothing here is a balance proposal that is applied anywhere.
**Data:** `docs/GC_ASCENSION_SIMULATION_REPORT.md` (generated, all tables), `scripts/ascension_analysis.py`, `scripts/player_journey_sim.py` (asc-model/1), `tests/test_ascension_simulation.py` (22 tests). Stacked on the bottleneck analysis (draft PR #558) and the player-journey simulator (draft PR #555).
**Baseline rules:** current `main`, **including the open outpost-XP defect** (PR #556 is not applied; its influence was measured separately, section 9). 730 days (24 months), 3 play styles, 1 planet (S1) and up to 11 planets (S11), mid-climate homeworld, policy v2, no paid accelerators, no loot, no Timekeeper skips.

## 1. Short answer

1. **There is no wall at L200.** The previous report stopped the mines at L200 because it used the resolver's nexus cap as a queue cap. Under `nodebuster-v1` the authoritative queue owner has no mine or solar cap. A competent player keeps deepening the mines at **about 2.6–2.9 days per level** (L200 → L300) and reaches **L308–L328 after 24 months**. Income at 24 months is **4–8x** the earlier figure and the queue is **60–73 % busy** in months 12–24 for active/optimizer players (earlier report: 1–8 % on one planet). Brake 4 of the bottleneck report was a model artefact (corrected in `docs/GC_PROGRESSION_BOTTLENECKS.md`).
2. **Ascension is an economic net loss at every tested threshold within 24 months.** Against "keep building" (`never`), income at 24 months is **−91…−92 %** for an Ascension at L200, **−85…−88 %** at L225, **−66…−79 %** at L250 and **−48…−50 %** at L300 on one planet (S1); with eleven planets −85…−88 %, −73…−80 %, −58…−68 % and −20…−35 %. With the canonical Trader the picture is the same (−67…−93 %).
3. **It does not catch up later either.** In an extended one-planet exploration (up to 72 months) no fixed threshold from L200 to L400 ever reaches the income of `never` (−80 … −99 % at 72 months).
4. **Three Ascensions of one mine are reachable in 24 months only for the economically worst strategies:** L200 (day 521–611 on one planet, 504–589 with eleven) and L225 (610–700 / 588–678); at L250 only the best players (day 711–719); at L300 never (one Ascension at most, day 630–698). Across 11 planets the empire as a whole completes 12–35 Ascensions at L200/L225 — each on its own mine with its own skill tree.
5. **The skill tree is out of reach.** AP per run: 1 / 2 / 3 / 6 / 11 / 16 at L200 / 225 / 250 / 300 / 400 / 500. The tree is **per mine**: the Overdrive gate (five core skills at rank 5) costs **50 AP**, the whole tree **339 AP** — 50 runs at L200 or 9 runs at L300 for *one* mine. A 24-month player earns **4–9 AP on a mine at best** (Frugal Rebuild rank 3–5, i.e. −16…−27.5 % rebuild cost). The breakthrough nodes additionally need a best depth of L300–L500.
6. **Why it loses, in one line:** one Ascension at L200 gives 1 AP and costs a rebuild of **85–91 days** (29–73 with the Trader) during which `never` deepens the mine by about **29 levels** — each worth +1.4…+2.6 % production and permanent. The mechanic is a deep valley: its payoff sits behind hundreds of AP that can only be earned by crossing the valley repeatedly.
7. **The outpost-XP defect does not change any of this** (11th world −2…+7 days; income differences of −12…+24 % are path-dependence noise that flips sign between styles).

What this does **not** say: it does not say Ascension is "broken" — it is a voluntary, multi-year prestige loop and the lifetime best depth keeps the ranking score. It says that **within the first two years the dominant decision is "do not ascend"**, so Ascension adds no decision depth in that window.

## 2. What was simulated, and what is canonical

| Area (task) | Canonical owner (executed, not re-implemented) | In the simulator | Not modelled |
|---|---|---|---|
| 1. Reset | `nodebuster.ascend_mine` (level ≥ L200, empty mine queue, one mine only, restart level `reset_start_level`, best depth kept) | the policy decides *when* to call it, with the planet's real buildings written to the sandbox DB first | request-id idempotency, vacation lock |
| 2. AP | `ascension_points_for_depth`, `skill_point_cost`, `skill_prerequisites_met`, `purchase_skill` | AP are granted only by the owner; skills bought only through `purchase_skill`; daily invariant: AP earned = Σ canonical awards, AP spent = Σ canonical skill costs | — |
| 3. Rebuild | `rebuild_bps_for_target` (cost/time discount while target ≤ best depth, +50 with Breakthrough Window), `rebuild_production_multiplier_for` (surge), exact `_scale_bps` integer math | cost, duration and production read the sandbox state through the same helpers the Buildings queue and the production formula use | — |
| 4. Deep mining | `power_upgrade_cost`, `power_build_seconds`, `building_progress_floor_seconds`, production formula with the UNI1 tail (pivot 120, q3), `_effective_building_queue_cap` (no mine/solar cap) | mines and solar levels beyond L200 are queued exactly as the owner allows; energy, storage (incl. Deep Storage) and tail bonus come from the `EffectResolver` hooks bound to the sandbox planet | Ascension of the fuel plant (never reaches L200 here) |
| 5. Repeated Ascensions | the same owner calls, any number of times | arms `T200`…`T400`; nothing is forced | — |
| 6. Comparison | — | casual / active / optimizer × 1 / up to 11 planets × 8 arms; extended exploration (S1, 72 months); Trader and construction-time sensitivities | Research-Lab Ascension, Stellar Forge, fleet transport between planets, loot, Timekeeper/Battle-Pass skips |

**Controlled design.** Every arm is the same policy (v2) with the same costs, queue depth and action windows. The arms differ from the old `legacy` model only once a mine passes L200 (verified day by day up to the first L200 in a 420-day probe; the committed test locks the first 60 days). The nexus buildings are still built at the old cap boundary (about 0.1 % of the mine spend; the geothermal nexus is genuinely needed because the depot maximum is 50 + 2 x its level).

**Ascension policy `T<n>`** (deliberately simple, legal, not optimal): ascend a production mine the first time it is at depth ≥ n with no mine job queued; only one mine per planet rebuilds at a time (income continuity); AP are spent in a fixed strict priority (`rebuild_first`: Frugal → Rapid → Reconstruction → Deep Yield → …; `yield_first`: Deep Yield first, i.e. `T200y`/`T250y`). Both orders give the same verdict.

## 3. Correction of the previous report

| 24 months | `legacy` (cap L200, previous report) | `never` (canonical queue) |
|---|---|---|
| S1 income (casual / active / optimizer) | 19.6 / 19.7 / 19.8 B per h | **126 / 149 / 158 B** per h |
| S11 income | 157 / 212 / 218 B | **606 B / 1.0 T / 1.1 T** |
| Best mine | L200 | **L308 / L321 / L325** (S1), L312 / L328 / L328 (S11) |
| Queue running, months 12–24 (S1 casual / active / optimizer) | 8 / 6 / 1 % (76–98 % "nothing to build") | 20 / 61 / 73 % |
| Production lost to full depots (S1 optimizer) | metal 79 %, crystal 83 % | metal 0 %, crystal 30 % |

Pace of the deepest mine (days; usually the crystal mine): L100 at 71–126, L150 at 210–272, **L200 at 340–410**, L250 at 473–541, L300 at 630–699 — so 2.6–2.9 days per level between L200 and L300. The **metal mine alone** needs 324–326 days from L200 to L300 (3.2–3.3 days per level; the crystal mine leads it by 39–45 days at L300), see `docs/GC_SIMULATOR_RECONCILIATION.md`. Construction time is **not** the brake past L200 either (section 11 of the report): construction time x0.5 leaves the depth unchanged (casual, same Nanofactory level: L308 → L307), the queue simply waits for metal instead.

## 4. Per profile: depth, Ascensions, AP, skills, rebuild, production, queue

`never` = keep building. `T200` / `T250` = ascend at the first L200 / L250. `_tr` = with the canonical Trader. Depth = deepest mine ever reached at 6 / 12 / 24 months. Income = empire metal + crystal per hour at 24 months. Rebuild = median days to climb back through the previous best depth. Queue = share of world-seconds the build queue ran in months 12–24.

| Profile | Arm | Max depth 6 / 12 / 24 mo | Income 24 mo | vs `never` / `never_tr` | Ascensions (max per mine) | AP earned / spent | Skill ranks (all mines) | Rebuild days | Queue 12–24 mo |
|---|---|---|---:|---:|---:|---:|---|---:|---:|
| S1 casual | `never` | L120 / L183 / L308 | 126.0B | - | 0 | 0 / 0 | - | - | 20% |
| S1 casual | `T200` | L120 / L183 / L200 | 11.7B | -91% | 4 (4) | 4 / 4 | frugal 3 | 91 | 19% |
| S1 casual | `T250` | L120 / L183 / L250 | 31.6B | -75% | 2 (2) | 6 / 6 | frugal 4 | 144 | 20% |
| S1 casual | `never_tr` | L124 / L191 / L318 | 143.1B | +13% | 0 | 0 / 0 | - | - | 21% |
| S1 casual | `T200_tr` | L124 / L191 / L200 | 15.0B | -90% | 5 (5) | 5 / 4 | frugal 3 | 73 | 26% |
| S1 casual | `T250_tr` | L124 / L191 / L250 | 30.5B | -79% | 3 (3) | 9 / 9 | frugal 5 | 101 | 26% |
| S1 active | `never` | L132 / L200 / L321 | 149.4B | - | 0 | 0 / 0 | - | - | 61% |
| S1 active | `T200` | L132 / L200 / L200 | 12.2B | -92% | 5 (5) | 5 / 4 | frugal 3 | 86 | 68% |
| S1 active | `T250` | L132 / L200 / L250 | 51.3B | -66% | 2 (2) | 6 / 6 | frugal 4 | 126 | 72% |
| S1 active | `never_tr` | L138 / L214 / L333 | 174.0B | +16% | 0 | 0 / 0 | - | - | 42% |
| S1 active | `T200_tr` | L138 / L200 / L200 | 13.9B | -92% | 9 (9) | 9 / 9 | frugal 5 | 45 | 79% |
| S1 active | `T250_tr` | L138 / L214 / L250 | 44.4B | -74% | 4 (4) | 12 / 12 | frugal 6 | 70 | 74% |
| S1 optimizer | `never` | L138 / L209 / L325 | 157.9B | - | 0 | 0 / 0 | - | - | 73% |
| S1 optimizer | `T200` | L138 / L200 / L200 | 13.1B | -92% | 5 (5) | 5 / 4 | frugal 3 | 85 | 80% |
| S1 optimizer | `T250` | L138 / L209 / L250 | 32.9B | -79% | 3 (3) | 9 / 9 | frugal 5 | 120 | 87% |
| S1 optimizer | `never_tr` | L140 / L215 / L339 | 189.3B | +20% | 0 | 0 / 0 | - | - | 22% |
| S1 optimizer | `T200_tr` | L140 / L200 / L200 | 13.7B | -93% | 14 (14) | 14 / 12 | frugal 6 | 29 | 65% |
| S1 optimizer | `T250_tr` | L140 / L215 / L250 | 47.2B | -75% | 6 (6) | 18 / 16 | frugal 7 | 47 | 56% |
| S11 casual | `never` | L120 / L187 / L312 | 606.4B | - | 0 | 0 / 0 | - | - | 62% |
| S11 casual | `T200` | L120 / L187 / L201 | 89.1B | -85% | 18 (4) | 18 / 15 | frugal 14 | 97 | 59% |
| S11 casual | `T250` | L120 / L187 / L250 | 257.6B | -58% | 7 (2) | 21 / 18 | frugal 14 | 147 | 61% |
| S11 casual | `never_tr` | L122 / L190 / L321 | 697.5B | +15% | 0 | 0 / 0 | - | - | 71% |
| S11 casual | `T200_tr` | L122 / L190 / L202 | 110.2B | -84% | 22 (5) | 22 / 21 | frugal 17 | 83 | 73% |
| S11 casual | `T250_tr` | L122 / L190 / L250 | 227.7B | -67% | 10 (2) | 30 / 28 | frugal 20 | 131 | 72% |
| S11 active | `never` | L138 / L212 / L328 | 1.0T | - | 0 | 0 / 0 | - | - | 60% |
| S11 active | `T200` | L138 / L200 / L200 | 142.6B | -86% | 31 (6) | 31 / 27 | frugal 22 | 75 | 62% |
| S11 active | `T250` | L138 / L212 / L250 | 323.6B | -68% | 15 (3) | 45 / 42 | frugal 28 | 121 | 63% |
| S11 active | `never_tr` | L140 / L219 / L340 | 1.2T | +17% | 0 | 0 / 0 | - | - | 69% |
| S11 active | `T200_tr` | L140 / L200 / L203 | 154.6B | -87% | 48 (9) | 48 / 46 | frugal 32 | 52 | 78% |
| S11 active | `T250_tr` | L140 / L219 / L250 | 384.8B | -67% | 19 (4) | 57 / 54 | frugal 32 | 84 | 78% |
| S11 optimizer | `never` | L140 / L213 / L328 | 1.1T | - | 0 | 0 / 0 | - | - | 70% |
| S11 optimizer | `T200` | L140 / L200 / L200 | 132.0B | -88% | 35 (5) | 35 / 28 | frugal 23 | 79 | 74% |
| S11 optimizer | `T250` | L140 / L213 / L250 | 380.2B | -66% | 15 (3) | 45 / 42 | frugal 28 | 120 | 74% |
| S11 optimizer | `never_tr` | L143 / L221 / L345 | 1.4T | +24% | 0 | 0 / 0 | - | - | 76% |
| S11 optimizer | `T200_tr` | L143 / L200 / L210 | 166.8B | -88% | 56 (8) | 56 / 50 | frugal 37 | 52 | 89% |
| S11 optimizer | `T250_tr` | L143 / L221 / L252 | 374.2B | -73% | 22 (3) | 66 / 64 | frugal 38 | 96 | 86% |

Reading guide:

* **First Ascension at L200** comes on day 349 (S1 optimizer), 364 (active), 409 (casual); after that the planet sits at an income cliff of **38–42 %** (median) until the mine is back.
* **Rebuild** takes 75–97 days (T200, no Trader) for ~200 levels, against 349–410 days for the first climb: the rest of the economy (research, the other mine, solar) makes the second climb about 4x faster — and it is still about 29 levels of lost deepening each time. Rebuild is resource-bound (metal), which is why the Trader shortens it (29–83 days) without changing the verdict.
* **S11 skill ranks** are spread over up to 22 independent trees (planet x mine); 14–38 ranks of Frugal Rebuild in total means on average **well under 2 ranks per mine** — AP cannot be pooled.
* The `legacy` row of the report shows production lost to full depots of 70–83 % at 24 months; in the canonical `never` run metal is no longer wasted (0–1 %), crystal still overflows by ~30 % (the Trader recovers some of it: `never_tr` is +13…+24 % income).

## 5. The AP economy (canonical arithmetic)

| Goal (per mine) | AP | Runs at L200 | at L250 | at L300 | at L400 |
|---|---:|---:|---:|---:|---:|
| Frugal Rebuild rank 5 (−27.5 % rebuild cost) | 9 | 9 | 3 | 2 | 1 |
| Deep Yield rank 5 (+12.5 % output) | 14 | 14 | 5 | 3 | 2 |
| five core skills at rank 5 (Overdrive prerequisite) | 50 | 50 | 17 | 9 | 5 |
| Core Resonance (also needs best depth L300) | 43 | 43 | 15 | 8 | 4 |
| Breakthrough Window (best depth L400) | 64 | 64 | 22 | 11 | 6 |
| whole tree | 339 | 339 | 113 | 57 | 31 |

| Skill set | Rebuild cost | Rebuild time | Restart level | Output |
|---|---:|---:|---:|---:|
| no skills | 100 % | 100 % | L0 | +0 % |
| Frugal 1 (what one L200 run buys) | 94.5 % | 100 % | L0 | +0 % |
| core skills rank 5 | 72.5 % | 67.5 % | L60 | +12.5 % |
| core rank 5 + Overdrive III | 65 % | 60 % | L96 | +27.5 % |
| all rank 10 + Overdrive III | 37.5 % | 30 % | L156 | +40 % |

The effects that would make a reset cheap (restart L96–L156, −35…−62 % cost, −40…−70 % time, the ×2 rebuild surge of Legacy Reconstruction) sit between 74 and 339 AP **per mine**. The single-mine record anchors in `docs/MINE_EVOLUTION.md` ("Full Breakthrough V4: L343 after 6 months") presuppose that state; reaching it takes years of play, not 24 months.

## 6. When would an Ascension pay, and when is "keep building" better?

Keep building is better as long as **forgone deepening during the rebuild** is worth more than the skills the run buys. Per run at L200: 29 levels (≈ +50…+110 % production of that mine, permanently) against 1 AP (= 1/2 Deep Yield rank = +1.25 % output, or −5.5 % on the next rebuild's cost). The ratio improves with depth (AP per run grows, production gain per level shrinks from +2.6 % at L200 to +1.4 % at L300) but the rebuild also grows (85 → 120–147 days from L200 to L250), so even at L300–L400 the extended runs stay far below `never` (−43…−48 % at 36 months for L400 on one planet, −80…−87 % at 72 months).

Rule of thumb for design discussion (not a value proposal): an Ascension can only be economically neutral if the rebuild takes about as few days as the player would otherwise need for a handful of new levels (≈ 3 days per level), i.e. a rebuild of ≲ 10 days instead of 85–150. That needs most of the discount tree, which in turn needs the Ascensions it would pay for.

## 7. Design observations (nothing applied; each needs its own gate)

1. **Ascension adds no decision depth in the first 24 months** — the dominant strategy is "never". If the intent is a multi-year prestige loop this is acceptable and the AP/tree scale is simply a late-game budget; if the intent is a meaningful choice within the first two years, the entry yield is the thing to measure next: AP per early run (L200–L250), the first-rank effects, and whether AP could be shared between the mines of a planet. This simulator can price any such candidate without touching the game (new arms), and the AP arithmetic above shows the order of magnitude required.
2. **Depth comes from the uncapped climb, not from Ascension.** After month 12 the player is a pure mine-pusher at ~3 days per level; research, storage and the nexus are secondary. The earlier finding that `storage_tech` and `buildtime_tech` are dominated options is unchanged.
3. **Late construction time is not a lever** (section 11 of the report), so a build-time resonance remains weak in the deep game as well; planet XP (colony chain) and upgrade cost remain the measurable resonance effects from the bottleneck report. Ascension does not interact with the colony gate (the 11th world arrives within a few days of the same day in every arm), so the PL10-vs-PL15 comparison can run on `never` / `T200` arms.
4. **Per-mine trees** multiply the AP budget by up to 22 on an 11-planet account. If that is intended as a long-term sink, fine; if not, it is the largest single multiplier between "AP earned" and "benefit felt".

## 8. Limits (read before quoting numbers)

* **Fixed-threshold policy.** `T<n>` is a legal, simple policy, not the optimum; a smarter timing might lose less, but the best arm at 72 months (L400) is still −80 %. The structural reason (forgone levels vs 1–16 AP) does not depend on timing details.
* **No transport between planets.** A real player could fund a colony's rebuild from the homeworld stock; the Trader sensitivity is the only cross-resource relief modelled. It uses a simple rule (trade only when it completes the purchase now; canonical rates, minimum, score guard and daily limit; no half trades, no reversal within a day).
* **Not modelled:** Research-Lab Ascension, Stellar Forge, loot/expeditions, military sinks, Timekeeper/Battle-Pass skips, alliance/commander/booster modifiers, Ascension of the fuel plant.
* **Cross-check reconciled (see `docs/GC_SIMULATOR_RECONCILIATION.md`).** The single-mine record control (`scripts/sim_ascension_breakthroughs.py`) needs 887 days from L200 to L300 because it prices neutral production modifiers, one mine and one currency; the journey player needs 324–326 for the metal mine (289–293 for the deepest mine, which is usually the crystal mine). Adding the journey's assumptions to the control one at a time reproduces the journey within +1.3 % (L200 → L300) and −4.3 % (L100 → L200); the 3.4x research modifier alone is more than the whole gap. The Ascension verdict does not depend on the control.
* **Path dependence.** Production grows 1.4–2.6 % per level, so ±2 levels is ±3–5 %; differences below about ±10 % at 6/12 months are noise. The Nanofactory (build-time building, treated as neutral by the payback policy) is built only when nothing better is affordable, so its level differs between runs; depth at 24 months does not depend on it.
* **Baseline includes the outpost-XP defect.** With the fix (PR #556 cherry-picked in a scratch checkout) the 11th world arrives −2…+7 days apart and income differs by −12…+24 % with sign changes between styles: noise, no systematic shift (report section 9). Re-run after #556 lands.
* Real telemetry from DEV/UNI1 (how many players actually reach L200, how many ascend) would settle which of these simulated players exists.

## 9. Reproduce

```bash
# main matrix: 2 topologies x 3 styles x 8 arms (24 months) + extended S1 (72 months); ~6 min on 10 workers
python scripts/ascension_analysis.py --workers 10 --out-json artifacts/ascension/latest.json --out-md docs/GC_ASCENSION_SIMULATION_REPORT.md
# sensitivities merged into the same report
python scripts/ascension_analysis.py --subset trader --out-json artifacts/ascension/trader.json
python scripts/ascension_analysis.py --subset levers --out-json artifacts/ascension/levers.json
python scripts/ascension_analysis.py --render-from artifacts/ascension/latest.json --trader-json artifacts/ascension/trader.json \
    --levers-json artifacts/ascension/levers.json --out-md docs/GC_ASCENSION_SIMULATION_REPORT.md
python -m pytest tests/test_ascension_simulation.py tests/test_player_journey_sim.py tests/test_progression_bottleneck_analysis.py
```

The outpost-fix sensitivity (`--subset outpost`, then `--sensitivity-json`) must be run in a checkout that contains the commits of PR #556.
