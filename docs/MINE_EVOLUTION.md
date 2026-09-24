# Mine Evolution / Nodebuster Ascension

Planet-scoped prestige loop for the three production mines.

**Owner:** `game/mine_evolution/`  
**Ruleset:** `nodebuster-v1`  
**Launch target:** UNI 1  
**Status:** implementation

---

## Goal

Mine progression stays unbounded, but high-level play gets a voluntary prestige loop:

1. Push one production mine as deep as you want.
2. From level 200 onward, Ascension becomes available.
3. Ascending resets **only that selected mine** to its current reconstruction baseline.
4. Run depth grants permanent Ascension Points (AP).
5. AP are spent in a permanent, per-mine skill tree.
6. Rebuild nodes make the climb back to the lifetime best cheaper and faster.
7. Production nodes provide permanent output.
8. The next run can push deeper without introducing a permanent max level.

Ascension is never a hard build gate. A player may ignore it and continue upgrading beyond
level 200 indefinitely.

---

## Scope and isolation

Evolvable production mines:

- `metal_mine`
- `crystal_mine`
- `fuel_cell_plant`

State is scoped by `(planet_id, building_type)`.

Ascending Ferronit does not reset, buff or unlock Crytite or Brennzellen. Ascending one
planet never affects the same mine on another planet.

Solar, storages, research lab, Orbital Shipyard and other systems keep their own owners.
Research-Lab Ascension and Stellar Forge remain separate mechanics.

---

## No hard cap

The EffectResolver still exposes the structural Nexus progression used by legacy/UI
systems, but the authoritative Buildings queue owner ignores that mine cap when the
Nodebuster ruleset is active.

For production mines under `nodebuster-v1`:

```text
player-visible max level = none
internal queue safety sentinel = 2,147,483,647
```

The sentinel is an implementation guard, not a gameplay cap.

Solar and non-mine buildings continue using their normal structural limits.

---

## Ascension threshold and AP

First voluntary Ascension:

```text
ASCENSION_MIN_LEVEL = 200
```

Points for one completed run:

```text
above = level - 200
AP = 1 + floor(above / 25) + floor(above / 100)
```

Reference values:

| Run depth | AP |
|---:|---:|
| 200 | 1 |
| 225 | 2 |
| 250 | 3 |
| 300 | 6 |
| 400 | 11 |
| 500 | 16 |

The curve has no hard upper bound. Deeper pushes grant more AP.

---

## Reset contract

Ascension is atomic:

1. Validate ownership / vacation state.
2. Lock the selected planet.
3. Finish due authoritative work.
4. Persist the canonical resource tick through the Ascension timestamp while the old run level is still active.
5. Require selected mine level >= 200.
6. Reject while that mine still has pending build jobs.
7. Compute AP from the current run depth.
8. Persist lifetime best depth and Ascension counters.
9. Reset only the selected mine to its reconstruction baseline.
10. Credit AP.
11. Commit.

No Tribute is charged in Nodebuster V1.

The initial reset baseline is level 0. Permanent Reconstruction skills can raise it.

A second request with the same `request_id` returns the cached result and cannot perform
another reset or grant AP twice.

---

## Permanent skill tree

Owner: `game/mine_evolution/nodebuster.py`

### Reconstruction

- Max rank: 10
- +12 restart levels per rank

### Frugal Rebuild

- Max rank: 10
- -5.5% mine upgrade cost per rank (rebuild only; full-tree floor 37.5% of normal cost)
- Active only while rebuilding at or below the lifetime best depth

### Rapid Rebuild

- Max rank: 10
- -6.5% mine build time per rank (rebuild only; full-tree floor 30% of normal time)
- Active only while rebuilding at or below the lifetime best depth

### Deep Yield

- Max rank: 10
- +2.5% permanent production per rank for that selected mine

### Deep Storage

- Max rank: 10
- +5% permanent storage capacity per rank
- Applies only to the resource produced by that selected mine on that planet
- Uses the canonical `EffectResolver.get_storage_capacity()` path

### Overdrive

- Max rank: 3
- Requires Reconstruction, Frugal Rebuild, Rapid Rebuild, Deep Yield and Deep Storage at rank 5
- Per rank:
  - +12 restart levels
  - +5% permanent production
  - -2.5% rebuild cost
  - -2.5% rebuild time

At the launch caps the maximum restart baseline is level 156, still below the
L200 Ascension activation threshold.

Skill costs rise with purchased rank. The browser receives the server-computed cost,
availability and affordability; it never calculates the tree economy itself.

---

## Rebuild contract

Rebuild discounts apply only when:

- the selected mine has completed at least one Ascension; and
- the target level is <= that mine's lifetime best depth.

Above the previous best, normal canonical mine costs and build times apply again.

All cost scaling uses exact integer basis-point math. No float conversion is used for
large resource costs.

The same modifier path is used by:

- single build enqueue
- MAX queue preview
- MAX queue cost total
- queue rescheduling
- Buildings card cost/time preview

This keeps displayed values and charged values identical.

---

## Production

Nodebuster production bonuses reuse the existing canonical production engine.

`ProductionContext.building_modifier` receives the permanent production multiplier for
the selected mine only.

No second production engine exists.

Fresh mine with no skill:

```text
building_modifier = 1.0
```

Deep Yield / Overdrive increase that multiplier for only the matching
`(planet_id, building_type)`.

Reconstruction Surge is intentionally separate from the permanent multiplier:

- `ProductionContext.mine_rebuild_modifier = 2.00` only while the current mine
  level is inside the authoritative rebuild window;
- it multiplies the **mine part only**, never the planet's standard income;
- without Breakthrough Window it ends at lifetime best depth;
- with Breakthrough Window it ends at lifetime best depth +50;
- outside that window the modifier returns exactly to `1.0`.

---

## Ranking / lifetime progression

A prestige reset must not destroy earned progression score.

Under Nodebuster, building progression valuation uses:

```text
scored_level = max(current_level, lifetime_best_depth)
```

for each evolvable mine.

Example:

```text
Ferronit reaches L300
→ Ascension
→ mine resets to L0/L10/...
→ ranking still values the mine at L300
→ score starts growing again only once the new run exceeds L300
```

This keeps Ascension a transformation of progression rather than a ranking penalty.

---

## Data

Migration: `178_nodebuster_mine_ascension.sql`

### `planet_mine_ascension_state`

| Column | Meaning |
|---|---|
| `planet_id` | Colony |
| `building_type` | Selected mine |
| `ascension_count` | Completed Nodebuster runs |
| `points_earned` | Lifetime AP earned |
| `points_unspent` | Available AP |
| `best_depth` | Lifetime highest completed run depth |
| `last_depth` | Most recent Ascension depth |
| `updated_at` | Timestamp |

PK: `(planet_id, building_type)`

### `planet_mine_ascension_skills`

| Column | Meaning |
|---|---|
| `planet_id` | Colony |
| `building_type` | Selected mine |
| `skill_key` | Node key |
| `skill_rank` | Permanent purchased rank |
| `updated_at` | Timestamp |

PK: `(planet_id, building_type, skill_key)`

The legacy `planet_mine_evolution` table remains for rolling compatibility but is not
the Nodebuster V1 progression owner.

---

## APIs

### Ascend

`POST /api/buildings/mine-evolve`

```json
{
  "building_type": "metal_mine",
  "request_id": "uuid"
}
```

Successful payload includes:

- run depth
- reset level
- AP gained
- AP lifetime / unspent
- best depth
- Ascension count

### Buy skill

`POST /api/buildings/mine-evolution/skill`

```json
{
  "building_type": "metal_mine",
  "skill_key": "rapid_rebuild",
  "request_id": "uuid"
}
```

The server validates rank cap, prerequisites, AP balance and ownership atomically.

---

## Buildings UI

The normal mine card is deliberately progressive-disclosure:

- always visible: mine identity, current level and the immediate build/Ascension action;
- one reveal: next-level time, effect and resource cost;
- deeper technical data: level tables, energy/production breakdown and formulas;
- the dedicated Skill Tree → Ascension tab owns AP, best depth, restart level,
  Ascension count and permanent skill-tree detail.

This keeps the building grid readable without deleting any power-user data.

The confirm modal explicitly shows:

- current run depth
- AP gain
- reset level
- lifetime-best preservation

No Tribute copy is shown for Nodebuster.

Client actions use `GC.fetchGameAction` and reconcile from canonical server state.

---

## Regression contract

Primary suites:

- `tests/test_mine_evolution.py`
- `tests/test_gc_mine_ascension_nexus_001.py`
- `tests/test_ascension_queue_cap_contract.py`
- `tests/test_gc_ferro_l388_001.py`

They lock:

1. voluntary Ascension from L200+
2. no mine hard gate at L200/L225/...
3. selected-mine-only reset
4. depth-sensitive AP
5. exactly-once request behavior
6. permanent reconstruction baseline
7. per-mine production skill isolation
8. per-mine/resource Deep Storage isolation
9. rebuild cost/time discounts
10. big-number-safe cost scaling
11. lifetime progression score preservation
12. Nodebuster ruleset identity

---

## UNI 1 launch

UNI 1's production config guard requires:

```text
ASCENSION_RULESET = nodebuster-v1
```

The universe must remain closed if the Nodebuster implementation or any other launch
contract gate is missing. See `docs/UNI1_LAUNCH_CONTRACT.md`.


---

## Ascension Breakthrough V4

V4 keeps the breakthrough structure, but rebases it around the launch q3 tail and
makes the reset/rebuild payoff materially stronger. It retains the removal of the duplicated restart mechanic
from the expensive Legacy keystone. The expensive nodes now change four different
parts of the prestige loop: endgame scaling, rebuild production, rebuild reach and
the second endgame scaling jump.

| Keystone | Cost | Gate | Permanent rule change |
|---|---:|---|---|
| Core Resonance | 15 AP | Deep Yield 8+, best depth L300 | Personal mine tail q3.00 -> q3.15 |
| Reconstruction Surge | 20 AP | Reconstruction 8+, best depth L400 | +100% **mine-only** production while rebuilding through the lifetime best |
| Breakthrough Window | 24 AP | Frugal 8+ and Rapid 8+, best depth L400 | Rebuild cost/time discounts **and Reconstruction Surge** remain active through best depth +50 |
| Singularity Excavation | 36 AP | Core Resonance, Overdrive III, best depth L500 | Personal mine tail q3.15 -> q3.30 |

The q-tail breakthroughs are **not** extra production multipliers. The Mine
Evolution owner exposes an integer hundredths delta into
`ProductionContext.mine_tail_power_bonus_hundredths`; the canonical
`game/production_formula.py` applies that delta only to the active q3 endgame
tail for the matching planet and mine.

Rollout safety remains unchanged:

- legacy/shadow endgame modes ignore personal q-tail breakthroughs;
- active mode uses global q3 plus the per-mine delta;
- levels at/below the endgame pivot remain unchanged;
- production math stays server-authoritative and no frontend formula exists.

### Long-horizon balance gate

`scripts/sim_ascension_breakthroughs.py` owns two deterministic long-horizon checks.

The primary comparison remains the self-funded one-mine curve: one Ferronit mine,
all generated value reinvested into itself. It reports 6-month (182.5 d) and
12-month (365 d) outcomes for baseline q3, the current +40% stack, q3.15/q3.30,
the combined stack, current max rebuild and full Breakthrough V4.

Current deterministic anchors:

| Scenario | Start | 6 months | 12 months | Days to L300 | Days to L500 |
|---|---:|---:|---:|---:|---:|
| Baseline q3 | 200 | 223 | 245 | 886.6 | 3758.3 |
| q3 + current +40% | 200 | 232 | 261 | 633.3 | 2684.5 |
| Core Resonance q3.15 | 200 | 225 | 249 | 796.7 | 3176.9 |
| Singularity q3.30 | 200 | 227 | 253 | 719.3 | 2704.0 |
| q3.30 + current +40% | 200 | 237 | 273 | 513.8 | 1931.4 |
| Current max rebuild | 156 | 246 | 315 | 319.3 | 1088.5 |
| Full Breakthrough V4 | 156 | 343 | 478 | 133.6 | 399.4 |

The deliberately hostile 11-world pooling stress reaches **L508 after six months**
and **L705 after twelve months**; the zero-resource-cost queue ceilings remain
L769 / L836. These are upper-bound stress values, not normal player forecasts.

The second path is deliberately hostile: **11 mature feeder worlds** are assumed
to mirror the record mine's output and pool 100% of that value into one target
mine. No spending on research, fleet, storage or feeder development is deducted.
The only non-resource constraint is the real `building_progress_floor_seconds`
queue floor. This makes it an upper-bound stress case rather than a player forecast.

GC-FERDI-DEEP-PACING-002 keeps the old queue floor unchanged through L400,
adds cubic record-pressure through L1000, then continues linearly without a cap
so the canonical big-number base-time curve remains dominant. A separate
zero-cost queue check
assumes upgrades cost nothing at all; from L200 it remains below roughly L775
after six months and L850 after twelve months. Therefore an 11-world pooled
account cannot approach L2000 in one year through normal queue completion.

Regression owners: `tests/test_ascension_breakthrough_v2.py` and
`tests/test_progression_time_floor.py`.
