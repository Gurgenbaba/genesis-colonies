# Mine Evolution / Industrial Ascension (EPIC-29)

Planet-scoped Ascension loop for the three production mines. **Phase 1 = Kern-Loop** (GC-2905 feel-fix: no level reset).

**Owner:** `game/mine_evolution/`  
**Tickets:** GC-2900…GC-2905 · GC-MINE-ASC-NEXUS-001  
**Status:** Phase 1 🔄

---

## Goal

Give high-level mines a meaningful cyclic decision without a production cliff:

1. Raise the mine through the normal **Nexus cap** toward level 200  
2. At level 200, pay a **Tribute** and complete Ascension I  
3. Keep the mine level; unlock the next level band for **that mine only** and gain a permanent, saturating production bonus  
4. Reach the next linear threshold and repeat  

No second production engine. Bonus registers on the existing Ferdi formula via `ProductionContext.building_modifier` **per mine / resource**.

---

## Naming

| Context | Term |
|---------|------|
| System / rank | **Mine Evolution** / Evolution Rank III |
| Player action | **Ascension** / Ascension einleiten |
| Avoid | Rebirth, Prestige Reset, Zurücksetzen |

---

## Phase 1 scope

| In | Out |
|----|-----|
| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Evolution trees / skill points |
| Planet-scoped rank **per mine** | Account-wide evolution |
| Tribute at rank milestone (no level reset) | Industrial Core / PE unlocks |
| Nexus progression through L200 + linear post-200 Ascension bands | Other buildings (solar, shipyard, …) |
| Existing server-authoritative Buildings queue | Parallel evolution/build queue |

Future (docs only until separate tickets):

- **Phase 2:** Evolutionspunkte + Spezialisierungsbäume (after live data)  
- **Phase 3:** Planetary Industrial Core → PE decisions  
- **Phase 4:** Other buildings with their own evolution mechanics  

---

## Buildings & caps (binding contract)

Before the first Ascension, production mines and Solar use the normal Nexus progression:

```text
nexus_production_cap = 50 + planet_core_nexus + 2 × geothermal_nexus
```

Both Nexuses cap at level 50, therefore the normal producer ceiling is **level 200**.

| Building / Rank | Effective build cap |
|-----------------|---------------------|
| production mine, Rank 0 | current Nexus cap, maximum L200 |
| production mine, Rank I | L225 |
| production mine, Rank II | L250 |
| production mine, Rank III | L275 |
| production mine, Rank IV | L300 |
| further ranks | `required_level(rank+1)` |
| `solar_plant` | Nexus formula only; no Mine Ascension |
| Storages / other | existing formulas unchanged |

**Important:** Ascension rank is stored by `(planet_id, building_type)`. Ascending Ferronit does not unlock levels for Crytite or Brennzellen. Each mine has its own progression gate and Tribute.

The resolver owns the structural Nexus cap. `game/buildings.py` owns the rank-aware enqueue cap because only that layer has the selected mine’s persisted Ascension rank. Existing legacy overlevel/catch-up levels are never reduced.

---

## Balance constants

Owner: `game/mine_evolution/formulas.py`.

```text
FIRST_EVOLUTION_LEVEL = 200
EVOLUTION_LEVEL_STEP = 25
required_level(n) = 200 + (n - 1) × 25
# I=200, II=225, III=250, IV=275, V=300, …

TRIBUTE_LOOKBACK_LEVELS = 40
TRIBUTE_FACTOR = 0.25

bonus(rank) = 0.55 × (1 - exp(-0.246 × rank^0.69))
building_modifier = 1 + bonus(rank)
```

Bonus anchors (tests): I ≈11.99 %, II ≈18.02 %, III ≈22.46 %, V ≈28.94 %, X ≈38.51 %, XX ≈47.13 % → 55 %.

### Tribute (milestone-based)

```text
M = required_level(next_rank)
target levels = (M - 40 + 1) … M   # Evo I: 161…200
```

Canonical cost = sum of upgrade costs **to reach** each target level (`get_upgrade_cost(building, target - 1)`), then × 25 % (integer `// 4`). Metal + Crytite only.

Catch-up: a L285 mine buying Evo I pays the **same** Tribute as a L200 milestone purchase. Each further Ascension uses its own higher milestone window.

Ascension blocked while the selected mine has pending `build_queue` jobs (after `finish_due_work`).

### Modifier isolation

| Evolution | Buffs |
|-----------|--------|
| Ferronit (`metal_mine`) | metal production only |
| Crytite (`crystal_mine`) | crystal only |
| Brennzellen (`fuel_cell_plant`) | fuel_cells only |

Forbidden: one shared planet-wide `building_modifier` or one shared mine rank that buffs/unlocks all three resources.

---

## Catch-up

L285 · Evo 0 → I(200)✓ → II(225)✓ → III(250)✓ → IV(275)✓ → V(300)✗ until level rises.

- One Ascension per request  
- Ranks strictly sequential (no skip)  
- Each Ascension: own milestone Tribute + confirm  
- Build headroom after an Ascension becomes available immediately on the same mine  

---

## Data

Table `planet_mine_evolution`:

| Column | Meaning |
|--------|---------|
| `planet_id` | Colony |
| `building_type` | `metal_mine` / `crystal_mine` / `fuel_cell_plant` |
| `evolution_rank` | Completed Ascensions (0 = never) |
| `updated_at` | Unix time |

PK: `(planet_id, building_type)` — this is the independence guarantee.

---

## API

`POST /api/buildings/mine-evolve`

Body: `{ "building_type": "metal_mine", "request_id"?: "…" }`

Atomic flow (single write TX / single DB checkout):

1. Vacation/safety probe on the mutation connection  
2. `finish_due_work`  
3. Re-read selected mine rank + level  
4. Threshold (`level >= required_level(rank+1)`)  
5. Compute Tribute at milestone  
6. Spend resources (`try_spend_resources_conn`)  
7. Selected mine rank +1 (level unchanged)  
8. Commit  

Guarantees:

- No Tribute without rank increase and vice versa  
- No level reset  
- Other mine ranks are unchanged  
- Same `request_id` twice → one Tribute, one rank (`get_idempotent_action` / `save_idempotent_action`)  
- Return `{ ok, state }` → client `applyActionState`  

---

## Production wire

`production_context_from_resolver` loads the planet’s evolution rank for the resource’s mine and sets `building_modifier = 1 + bonus(rank)` for **that resource only**.

---

## UI

Building cards (resources tab): current Nexus/Ascension max level, evolution badge, progress `current / required`, Ascension confirm modal with benefit + Tribute (no reset warning). After a successful Ascension the selected card must immediately expose the newly unlocked level band. Server authority only — no client bonus/tribute math.

---

## Regression contract

`tests/test_gc_mine_ascension_nexus_001.py` proves the live gameplay chain:

1. Max Nexuses → mine cap L200  
2. Ferronit L200 / Rank 0 cannot queue L201  
3. Ferronit Ascension I succeeds without level reset  
4. Ferronit card/queue cap becomes L225 and L201 can be queued  
5. Crytite remains Rank 0 / cap L200 at the same time  

---

## Ticket map

| Ticket | Focus |
|--------|--------|
| GC-2900 | Master doc + EPICS / CORE §17 / BUILDINGS / PRODUCTION / ROADMAP |
| GC-2901 | Migration + owner + evolve API |
| GC-2902 | `building_modifier` wire in `production_context_from_resolver` |
| GC-2903 | Buildings UI + Confirm + Locales |
| GC-2904 | Integration tests |
| GC-2905 | No reset; Tribute@milestone; bonus curve; catch-up; atomic/idempotent |
| GC-MINE-ASC-NEXUS-001 | Restore Nexus→L200 contract + per-mine post-200 unlock bands |
