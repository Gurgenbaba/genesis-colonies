# Mine Evolution / Industrial Ascension (EPIC-29)

Planet-scoped Ascension loop for the three production mines. **Phase 1 = Kern-Loop** (GC-2905 feel-fix: no level reset).

**Owner:** `game/mine_evolution/`  
**Tickets:** GC-2900…GC-2905  
**Status:** Phase 1 🔄

---

## Goal

Give high-level mines a meaningful cyclic decision without a production cliff:

1. Push mine level toward an Ascension threshold  
2. Pay a **Tribute** (resources at the rank milestone)  
3. Keep the mine level; gain a permanent, saturating production bonus  
4. Face the next linear threshold for the following Ascension  

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
| Planet-scoped rank per mine | Account-wide evolution |
| Tribute at rank milestone (no level reset) | Industrial Core / PE unlocks |
| Linear thresholds + catch-up | Other buildings (solar, shipyard, …) |
| Nexus-limited normal progression to **L200**, then Ascension gates every +25 levels | Permanent hard max on mines |

Future (docs only until separate tickets):

- **Phase 2:** Evolutionspunkte + Spezialisierungsbäume (after live data)  
- **Phase 3:** Planetary Industrial Core → PE decisions  
- **Phase 4:** Other buildings with their own evolution mechanics  

---

## Buildings & caps (contract)

| Building | Cap (Phase 1) |
|----------|----------------|
| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Nexuses unlock normal levels up to **L200**. At L200 Ascension I is required; each completed Ascension unlocks the next **25 mine levels** (225, 250, 275, ...). |
| `solar_plant` | unchanged: `50 + core + 2×geo` |
| Storages / other | unchanged |

**Canonical contract:** Nexuses are the normal building-limit system and can unlock mines only up to L200. Ascension begins exactly there and takes over further mine progression in 25-level steps. Existing overlevel/catch-up levels are never reduced.

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

Ascension blocked while the mine has pending `build_queue` jobs (after `finish_due_work`).

### Modifier isolation

| Evolution | Buffs |
|-----------|--------|
| Ferronit (`metal_mine`) | metal production only |
| Crytite (`crystal_mine`) | crystal only |
| Brennzellen (`fuel_cell_plant`) | fuel_cells only |

Forbidden: one shared planet-wide `building_modifier` that buffs all three resources.

---

## Catch-up

L285 · Evo 0 → I(200)✓ → II(225)✓ → III(250)✓ → IV(275)✓ → V(300)✗ until level rises.

- One Ascension per request  
- Ranks strictly sequential (no skip)  
- Each Ascension: own milestone Tribute + confirm  

---

## Data

Table `planet_mine_evolution`:

| Column | Meaning |
|--------|---------|
| `planet_id` | Colony |
| `building_type` | `metal_mine` / `crystal_mine` / `fuel_cell_plant` |
| `evolution_rank` | Completed Ascensions (0 = never) |
| `updated_at` | Unix time |

PK: `(planet_id, building_type)`.

---

## API

`POST /api/buildings/mine-evolve`

Body: `{ "building_type": "metal_mine", "request_id"?: "…" }`

Atomic flow (single write TX):

1. `finish_due_work`  
2. Re-read rank + level  
3. Threshold (`level >= required_level(rank+1)`)  
4. Compute Tribute at milestone  
5. Spend resources (`try_spend_resources_conn`)  
6. Rank +1 (level unchanged)  
7. Commit  

Guarantees:

- No Tribute without rank increase and vice versa  
- Same `request_id` twice → one Tribute, one rank (`get_idempotent_action` / `save_idempotent_action`)  
- Return `{ ok, state }` → client `applyActionState`  

---

## Production wire

`production_context_from_resolver` loads the planet’s evolution rank for the resource’s mine and sets `building_modifier = 1 + bonus(rank)` for **that resource only**.

---

## UI

Building cards (resources tab): evolution badge, progress `current / required`, Ascension confirm modal with benefit + Tribute (no reset warning). Server authority only — no client bonus/tribute math.

---

## Ticket map

| Ticket | Focus |
|--------|--------|
| GC-2900 | Master doc + EPICS / CORE §17 / BUILDINGS / PRODUCTION / ROADMAP |
| GC-2901 | Migration + owner + evolve API + uncapped mines |
| GC-2902 | `building_modifier` wire in `production_context_from_resolver` |
| GC-2903 | Buildings UI + Confirm + Locales |
| GC-2904 | Integration tests |
| GC-2905 | No reset; Tribute@milestone; bonus curve; catch-up; atomic/idempotent |
