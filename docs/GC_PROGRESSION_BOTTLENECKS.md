# GC — Progression Bottlenecks: Where the Time Goes

**Status:** measurement and proposals only. Nothing here is a balance change, a formula change or a deployment.
**Data:** `docs/GC_PROGRESSION_BOTTLENECK_REPORT.md` (generated, all tables), `scripts/progression_bottleneck_analysis.py`, `tests/test_progression_bottleneck_analysis.py`. Built on the sandboxed player-journey simulator (draft PR #555), which runs the canonical economy owners (`EffectResolver`, `economy_balance`, `buildings`, `research`, `planet_level`, `dna_analysis`, `expansion_protocol`, `colonize_planet`) against a throw-away SQLite database.
**Baseline rules:** current `main`, including the open outpost-XP defect (PR #556 is not applied). 730 days, mid-climate homeworld, no paid accelerators, no loot, no Timekeeper skips.

## 1. The short answer: why is the build queue idle 93–97 % of the time?

The 3–7 % queue utilisation of the first player-journey report is **mostly a property of the simple decision policy (v1), not of the game rules.**

| 12 months, share of world-seconds | Queue running | Waiting for resources / depot / energy | Player latency | Nothing to build |
|---|---:|---:|---:|---:|
| v1 (goal list, round-robin research), optimizer, 1 planet | 4.9 % | 95.1 % | 0 % | 0 % |
| v2 (improved legal policy), optimizer, 1 planet | 56.0 % | 43.9 % | 0 % | 0 % |
| v2, active, 1 planet | 43.8 % | 41.5 % | 14.7 % | 0 % |
| v2, casual, 1 planet | 36.1 % | 29.7 % | 34.2 % | 0 % |
| v2, active, up to 11 planets | 42.6 % | 37.3 % | 20.1 % | 0 % |

* **v1** spent 54 % of its metal on research at 6 months, levelled `storage_tech` and `buildtime_tech` to 61–67 and kept both mines in lockstep. **v2** (payback-ranked purchases, saving for the best one, dynamic priority by bottleneck; same costs, queue depth and action windows) spends 80–96 % of its metal on mines in the first year, reaches **6–9x the income of v1 at 6 months on one planet** (about 2x with eleven planets) and keeps the queue 35–74 % busy in the first year.
* What remains is **rule-bound**: with competent play the build queue is waiting for **metal** (26–54 % of the time for the optimizer in months 0–12). Crystal is almost never the binding resource, fuel never appears (no building or research costs fuel).
* **Player latency** (affordable but nobody acts) is a play-pattern effect: 34 % (casual) / 15–20 % (active) of the time in the first year, 0 % for an always-online player.
* **After about month 12 the queue is idle for a different reason:** the mines hit the pre-Ascension cap (section 3, brake 4) and there is *nothing left to build*.

## 2. Rule or artefact? (classification used by the report)

| Cause | Source | Verdict |
|---|---|---|
| Wait for metal / crystal | cost growth vs income | **Rule** (the core economy loop) |
| Wait for a depot upgrade, energy drag, research prerequisite | storage/energy/research rules | **Rule**, but small (energy drag 0.0 %, depot build 0–3 %, prerequisite wait 0 %) |
| Player latency | action windows (casual 2/day, active 4/day) | **Play pattern**, not a rule |
| Nothing to build | content exhausted (cap) or policy has no goal | **Content/model limit** (Ascension and other sinks are not modelled) |
| Research choices (round-robin vs payback) | decision policy | **Policy artefact** — but also a decision-quality finding (section 3) |

## 3. The five biggest progression brakes (policy v2, i.e. competent legal play)

Impact = change of empire income (metal + crystal per hour) at 6 / 12 / 24 months when the brake is removed or relieved in the sandbox (counterfactual lever; mean over casual / active / optimizer). Small deltas (below about ±10 %) at 6/12 months are path dependence of the fixed policy; the energy lever, which is not a brake, swings −11 % … +3 %. For small effects the report therefore also gives the *day the mine cap is reached* and the *day of the 11th world*, which are stable.

| # | Brake | Evidence | 6 mo | 12 mo | 24 mo |
|---|---|---|---:|---:|---:|
| 1 | **Cost growth vs. income** (incl. the research resource sink) | metal wait is the largest rule-bound idle cause; +25 % income raises income by about 3x that at 6 months (compounding) | +25 % income → **+83 % / +120 %** (1 planet / 11) · free research cost **+99 % / +40 %** | +37 % / +65 % · +22 % / +6 % | +25 % / +26 % · +0 % |
| 2 | **Serial planet-level-15 colony chain** (S11) | 85–95 % of the horizon is spent at the maturity gate; 48–70 days per colony; 11th world on day **448 / 481 / 642** (optimizer / active / casual); gate speed is set by planet XP (PL15 = 6 651 XP, scan 120 XP/day/world), not by the economy | removed: **+86 %** (+3 worlds @12 mo) | **+113 %** | +12 % |
| 3 | **Player latency** (play pattern) | casual earns **31 % / 60 % / 99 %** (1 planet) and **18 % / 40 % / 72 %** (11 planets) of the optimizer's income at 6 / 12 / 24 months; active 72 / 98 / 100 % and 77 / 87 / 97 % | see left | | |
| 4 | **Pre-Ascension cap reached, then no sink** | mines reach L200 on day **350–412** (1 planet) / **341–399** (11 planets); months 12–24: *nothing to build* 76–99 % (1 planet), 34–60 % (11); 71–79 % of all metal produced in 24 months lost to full depots; research queue 89–97 % busy (the only remaining growth axis: instant research +25 % / +19 % income at 24 months) | – | – | **income flat** (x1.1 from month 12 to 24 for active/optimizer, 1 planet) |
| 5 | **Depot capacity and resource imbalance** | crystal lost to full depots 22–37 % in the first 12 months (metal is binding, crystal over-supplied); unlimited depots **+36 % / +43 %** at 6 months; fuel is 99 % unused (no modelled sink) | +36 % / +43 % | +15 % / +19 % | +0 % / +4 % |

**Not brakes (measured):** *energy* (drag 0.0 %, ≤ 0.03 % of metal production lost; competent players keep the ratio ≥ 0.98; the lever swings −11 % … +3 %, i.e. noise), *construction duration* (making builds 99 % faster gives +5 % / +19 % at 6 months (1 planet / 11), +0 % / +8 % at 12 months and about +1 % at 24 — the queue is waiting for resources, not for timers), *research duration* (negative early because faster research drains the metal that builds mines; positive only after the cap).

**Decision-quality finding:** under payback ranking `storage_tech` ends at level 3–5 and `buildtime_tech` at 0, while the simple policy bought 61–67 of each and ended with a fraction of the income. In this economy those two techs behave like **dominated options** — an interesting-decisions issue, independent of speed (confirm against Ascension and loot once those are modelled).

### Time to the cap (day the best metal mine reaches the level)

| Policy | Style | 1 planet L100 / L150 / L200 | 11 planets L100 / L150 / L200 |
|---|---|---|---|
| v2 | casual | 129 / 275 / 412 | 124 / 270 / 399 |
| v2 | active | 89 / 234 / 366 | 82 / 214 / 344 |
| v2 | optimizer | 74 / 218 / 350 | 75 / 212 / 341 |
| v1 | active | 159 / 386 / 542 | 109 / 270 / 416 |

The cap is the designed **pre-Ascension** limit (base 50 + planet-core nexus 50 + 2 x geothermal nexus 50 = 200, `EffectResolver.get_max_building_level`). Progress beyond it is the Ascension loop, which the simulator does **not** model (AP is reported as potential only). The record-mine upper bounds of the economy audit (L237 / L273) include Ascension; the sandbox runs therefore stop at L200 by construction.

## 4. What this means for trait resonances (R3)

The earlier ±1–2 % result for a 5–12 % build-time resonance was not a policy accident — build time is simply not what limits progression. Equal-strength levers (about 10 %, applied empire-wide in the sandbox; policy v2, mean over styles):

| Candidate effect (≈10 %) | Mines to L200 (1 planet) | Mines to L200 (11 planets) | 11th world | Verdict |
|---|---:|---:|---:|---|
| Construction time −12 % | +5 d | −4 d | −2 d | no effect (≈ noise) |
| Research time −12 % | +4 d | +1 d | ±0 d | no effect |
| Depot capacity +10 % | −0 d | −0 d | −1 d | no effect |
| Research cost −10 % | ±0 d | −6 d | −3 d | small |
| **Mine / solar upgrade cost −10 %** | **−14 d** | **−24 d** | +4 d | **real**, about 4–7 % faster to the cap |
| **Colony planet XP +10 %** | – | +2 d | **−48 d (−9 %)** | **real** on the expansion chain |
| Colony planet XP +25 % | – | +2 d | **−107 d (−20 %)** | strong |

Consequence for the R3 design space (not a decision): the two effects with a measurable, *bounded* impact are **planet XP of the colony under development** (the exact brake of the serial PL15 chain) and **upgrade cost of the production buildings** of the qualified planet. Build time, research time and depot capacity should not be the headline of a resonance. Caveat: the levers act empire-wide; R3 limits a resonance to one qualified planet, so the real effect on a multi-planet empire is diluted (to be measured with one-world variants, next step).

## 5. Proposals (nothing applied; each needs a gate before implementation)

1. **Colony chain: lower or stage the maturity gate, or accelerate the colony under development.** Measured: gate at **PL10** puts the 11th world on day **308** (−216 d) with income +26 % / +42 % / +11 % at 6/12/24 months; **PL5** day 195; **+25 % colony XP** day 417 (−107 d). *Gate before implementation:* rank dispersion and "median vs best world" in the S11 simulation, colony-spam check for the late-slot mandates (slots 7–10), and the interaction with PR #556 (re-run the baseline once it is merged).
2. **Optional "reserve next purchase" (queue ahead).** A purchase the player cannot afford yet is reserved and starts by itself when the funds arrive. No formula changes. Measured for a casual player: income **+52 % / +36 % / 0 %** (1 planet) and **+36 % / +20 % / +1 %** (11 planets) at 6/12/24 months; casual's share of the optimizer's income rises from 31 % to 47 % (1 planet) and 18 % to 24 % (11 planets) at 6 months. Cost: a committed pick can be stale (−11 % for an optimizer with eleven planets), so it must be cancellable. *Gate:* UI/queue-owner design and an abuse review (cost is deducted at start, never at reservation).
3. **Define the post-cap loop before tuning anything else.** Active competent players reach the pre-Ascension cap at month 11–13 and the build queue then has nothing to do. Whether that is a dead end or the intended hand-over to Ascension cannot be decided from this data: **model the Ascension rebuild loop (AP gain vs rebuild time) and the late sinks (static hulls / Forge, Trader, DNA scans) next.**
4. **Resource balance (crystal over-supply, idle fuel).** Crystal is lost to full depots (22–37 % in year 1) while metal binds; fuel production is unused in everything the simulator models. Before changing mine cost ratios, check what the Trader/exchange and fleet fuel consumption (both not modelled) already absorb.
5. **Tech decision space.** `storage_tech` and `buildtime_tech` are dominated in the modelled economy. Decide whether they should matter earlier (e.g. depot-bound moments, Ascension rebuilds) or be re-purposed; do not touch values before the Ascension model exists.

## 6. Limits of this analysis

* **No Ascension, Trader, fleet/fuel consumption, military sinks, loot, Timekeeper skips or expeditions** (beyond the XP sensitivity of the earlier report). Brakes 4 and 5 are therefore partly *model limits* and are labelled as such.
* **Policies are assumptions.** v2 uses exact EffectResolver look-ahead for payback ranking (a good human approximates it), and action windows are assumptions about when players are online. Real queue telemetry from DEV/UNI1 would settle how close casual/active/optimizer are to real players — this is the cheapest next validation.
* **Levers are counterfactuals**, applied empire-wide; they say what a brake costs, not that it should be removed. Early-income deltas below about ±10 % are path dependence.
* **Baseline includes the outpost-XP defect** (PR #556 not applied): colonies become unrestricted through colonise XP. The sandbox builds the establishment milestones first, so the effect on the numbers is expected to be small, but it has not been re-measured.
* One climate (mid), one homeworld DNA seed for the S11 runs, no hot/cold sweep in this analysis.

## 7. Reproduce

```bash
python scripts/progression_bottleneck_analysis.py --out-json artifacts/progression_bottlenecks/latest.json --out-md docs/GC_PROGRESSION_BOTTLENECK_REPORT.md   # ~6 min on 10 workers
python scripts/progression_bottleneck_analysis.py --render-from artifacts/progression_bottlenecks/latest.json --out-md docs/GC_PROGRESSION_BOTTLENECK_REPORT.md
python -m pytest tests/test_progression_bottleneck_analysis.py tests/test_player_journey_sim.py
```
