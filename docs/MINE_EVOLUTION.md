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
- +10 restart levels per rank

### Frugal Rebuild

- Max rank: 10
- -4% mine upgrade cost per rank
- Active only while rebuilding at or below the lifetime best depth

### Rapid Rebuild

- Max rank: 10
- -5% mine build time per rank
- Active only while rebuilding at or below the lifetime best depth

### Deep Yield

- Max rank: 10
- +2.5% permanent production per rank for that selected mine

### Overdrive

- Max rank: 3
- Requires Reconstruction, Frugal Rebuild, Rapid Rebuild and Deep Yield at rank 5
- Per rank:
  - +10 restart levels
  - +5% permanent production
  - -2% rebuild cost
  - -2% rebuild time

At the V1 caps the maximum restart baseline is level 130.

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

Each mine card exposes one compact Nodebuster surface:

- current run level
- AP available
- AP gained if Ascending now
- lifetime best depth
- current restart level
- Ascension count
- permanent rebuild / production bonuses
- five-node permanent skill tree
- Ascend CTA from level 200 onward

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
8. rebuild cost/time discounts
9. big-number-safe cost scaling
10. lifetime progression score preservation
11. Nodebuster ruleset identity

---

## UNI 1 launch

UNI 1's production config guard requires:

```text
ASCENSION_RULESET = nodebuster-v1
```

The universe must remain closed if the Nodebuster implementation or any other launch
contract gate is missing. See `docs/UNI1_LAUNCH_CONTRACT.md`.
