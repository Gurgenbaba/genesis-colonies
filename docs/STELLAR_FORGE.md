# Stellar Forge — Orbital Shipyard Ascension (EPIC-30)

Planet-scoped endgame Ascension loop for `orbital_shipyard`, sibling to [MINE_EVOLUTION.md](MINE_EVOLUTION.md) (EPIC-29) but campaign-shaped instead of single-tribute: a rank-up requires clearing **four pillars** (Tribute, Manufacturing Trial, Operational Trial, Forge Cores), not just paying resources.

**Owner:** `game/stellar_forge/` (sibling to `game/mine_evolution/`)
**Tickets:** GC-3000…GC-3007
**Status:** ✅ Phase 1 implemented (`tests/test_stellar_forge.py`)

---

## Goal

Give a maxed-out `orbital_shipyard` a meaningful, repeatable Ascension loop that:

1. Sinks resources at the **planet**, not the empire — forces transport/logistics play, not a wallet check.
2. Requires **new** production (Hull Mass produced *after* the campaign starts), not counting the existing fleet.
3. Requires using other live systems (Fleet missions, Combat, Expedition, Recycler) to close a rank.
4. Grants **capability unlocks per rank**, not raw build-speed multipliers that would blow out ship-count inflation further.

No second shipyard engine. Stellar Forge reads/writes its own rank state and layers modifiers onto the existing shipyard math in `game/shipyard.py` — it does not reimplement batch capacity, build time, or the build queue.

---

## Naming

| Context | Term |
|---|---|
| System / rank | **Stellar Forge** / Forge Rank III |
| Player action | **Ascension Campaign** / Campaign starten |
| Avoid | Rebirth, Prestige Reset, Werft zurücksetzen |

---

## Correction vs. the original pitch

An earlier draft of this feature assumed shipyard formulas of `unit_seconds = build_seconds × 0.9^(yard_level−1)`, `yard_capacity = 3^yard_level`, and a hull-mass weight of `ceil(build_seconds / 5)`. **None of these exist in the codebase.** The real formulas, confirmed in `game/shipyard.py`:

- Batch capacity: `orbital_production_batch_capacity(lvl) = floor(1 + lvl*5 + lvl**2.3)` (`game/shipyard.py:49-52`)
- Build-time level discount: `BUILD_TIME_LEVEL_FACTOR = 0.975` per level above 1 (`game/shipyard.py:22`), i.e. `reduction = 1 - 0.975**(lvl-1)`
- Order duration: `ceil(amount / batch_capacity) × unit_seconds` (`production_job_duration_seconds`, `game/shipyard.py:127-131`)
- There is no fixed level cap ("50") on `orbital_shipyard` — max level comes from `EffectResolver.get_max_building_level()` (`game/buildings.py:650-651`), driven by tech/building `max_level` effects. Stellar Forge's unlock threshold must read this dynamically, not hardcode 50.

Hull Mass (new concept for Manufacturing Trials) must be defined fresh — see Pillar 2 below — it does not reuse `build_seconds` as a mass proxy on its own; it's derived from actual `build_cost` (resource investment), which is a truer "how much did this ship cost to make" signal than base build time.

---

## Phase 1 scope

| In | Out |
|---|---|
| `orbital_shipyard` only | Other buildings' own Ascension mechanics |
| Planet-scoped rank per shipyard | Account-wide Forge rank |
| 4-pillar campaign per rank (Tribute / Manufacturing / Operational / Forge Cores) | Skill trees, Capital Hulls, Overdrive |
| Ranks I–III, capability unlocks only (extra queue slot, Ascension HUD, Nanite-Assisted order option) | Specialization (Vanguard/Logistics/Odyssey forge), Redline Overdrive, Capital Hulls |
| Forge Cores as a new collectible currency, sourced from existing endgame content (World Boss, Expedition, Recycler) | New content generators built solely to drop Forge Cores |

Future (docs only until separate tickets, own EPIC-30 sub-numbers):

- **Phase 2:** Forge Specialization (per-planet ship-category bonus, exclusive choice)
- **Phase 3:** Industrial Overdrive (timed throughput buff, resource-burn tradeoff)
- **Phase 4:** Capital Hulls (Hull-Mass-gated ship tier)

---

## Unlock condition

`orbital_shipyard` level `>= get_max_building_level(planet_id, "orbital_shipyard")` (i.e. the planet's shipyard is at its *current* effective cap, whatever tech/effects have pushed that to). Re-evaluated each time effects change — do not snapshot "50" anywhere.

---

## The four pillars (per rank)

A rank's campaign is a row in `planet_shipyard_ascension` with four independent progress fields. All four must read `complete` before `POST /api/shipyard/forge-ascend` accepts.

### Pillar 1 — Industrial Tribute (resource sink, planet-scoped)

Cost is **not** a flat constant. It scales off the planet's own trailing production, read from the existing production resolver (no new formula engine):

```text
tribute_hours(rank) = 24 + (rank - 1) * 12   # I=24h, II=36h, III=48h, ...
tribute_resources = trailing production for (metal, crystal, fuel_cells) over tribute_hours(rank),
                     weighted 55% metal / 30% crystal / 15% fuel_cells
```

Must be **paid from the shipyard planet's own stockpile** (`try_spend_resources_conn` scoped to `planet_id`), same pattern as Mine Evolution's Tribute spend — this is what forces transport gameplay instead of an empire-wide auto-deduct.

### Pillar 2 — Manufacturing Trial (new production only)

New metric: **Hull Mass**, defined per ship as `sum(build_cost.metal, build_cost.crystal, build_cost.fuel_cells * 3)` at production-complete time (fuel_cells weighted 3x — they're the scarcer resource per `docs/ECONOMY_SYSTEM.md`). Computed at the point a shipyard order **completes**, not from the existing fleet snapshot.

```text
manufacturing_target(rank) = base_hull_mass(rank) with category requirement:
  - the campaign's 3 rolled categories (below) must each have Hull Mass > 0
```

No per-category cap (dropped post-launch — GC-3008): ship unit costs vary too much by
tier (a capital combat hull can be 10x+ the Hull Mass of a scout/cargo unit at the same
quantity) for a flat 60%-of-total ceiling to be a fair signal. The UI still shows the
per-role % breakdown for transparency, just without a hard block.

**Rolled categories (GC-3009):** "any 3 categories of your choice" let players always
pick the 3 cheapest ships, defeating the diversification intent. `start_campaign` now
rolls 3 distinct categories at random from `MANUFACTURING_ROLE_POOL` (all ship roles
except `colony` — Seed Ark stays rare/limited-purpose, not a Hull Mass grind target)
via `roll_manufacturing_roles()`, stored in `planet_shipyard_ascension.manufacturing_roles`
(migration `151_stellar_forge_manufacturing_roles.sql`) and reset to `[]` on ascend.
`manufacturing_trial_complete(total, rank, by_role, required_roles)` checks total ≥
target **and** every required role has `by_role[role] > 0` — falls back to the old
"any 3 distinct roles" behavior when `required_roles` is empty (campaigns started
before this shipped).

Counter resets to 0 at campaign start; only orders completed **after** `campaign_started_at` count. Implemented as a running counter column, incremented inside the shipyard order-completion path (wherever `game/shipyard_queue.py` finalizes a build), not recomputed from history.

### Pillar 3 — Operational Trial (use other live systems)

Pick-3-of-5 checklist per rank, backed entirely by existing systems — no new mission engine:

| Protocol | Source system |
|---|---|
| Exploration Protocol | `game/fleet.py` expedition mission completions |
| Salvage Protocol | Recycler / wreckage salvage value ([GC-584_WRECKAGE_SALVAGE.md](GC-584_WRECKAGE_SALVAGE.md)) |
| Warfare Protocol | Fleet-value destroyed via `simulate_battle()` combat reports |
| Titan Protocol | Damage dealt to a World Boss ([WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md)) |
| Logistics Protocol | Resources moved between own colonies via Fleet transport missions |

### Pillar 4 — Forge Cores (rare progression item)

New collectible currency (`forge_core` inventory item), **not resource-purchasable**. Dropped by World Boss, high-tier Expedition events, Recycler rare finds, Season objectives — reuses existing drop-table infrastructure (`docs/LIVEOPS_RETENTION.md` / `docs/GENESIS_STORY_OPS.md` drop plumbing), not a new loot engine.

```text
forge_cores_required(rank) = 3 + (rank - 1) * 4   # I=3, II=7, III=11
```

---

## Rank rewards (capability unlocks, not raw speed)

Deliberately **not** a flat build-time or batch-capacity multiplier — Phase 1 must not reopen the ship-count-inflation problem Mine Evolution's Tribute/no-reset design was built to avoid.

| Rank | Unlock |
|---|---|
| I | +1 shipyard queue slot; Ascension HUD; Manufacturing statistics panel |
| II | "Nanite-Assisted" order option: +25% build speed for that order, +35% fuel_cells cost (opt-in per order, not a permanent multiplier) |
| III | Forge Specialization slot unlocked (docs-only in Phase 1 — implementation is Phase 2) |

---

## Data

New migration `150_stellar_forge.sql` (template: `migrations/148_mine_evolution.sql`):

```sql
CREATE TABLE IF NOT EXISTS planet_shipyard_ascension (
    planet_id INTEGER NOT NULL,
    forge_rank INTEGER NOT NULL DEFAULT 0,
    campaign_active INTEGER NOT NULL DEFAULT 0,
    campaign_started_at REAL,
    tribute_paid INTEGER NOT NULL DEFAULT 0,
    hull_mass_progress INTEGER NOT NULL DEFAULT 0,
    hull_mass_by_role TEXT NOT NULL DEFAULT '{}',   -- JSON: {role: hull_mass}
    operational_protocols_done TEXT NOT NULL DEFAULT '[]',  -- JSON list
    forge_cores_committed INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (planet_id),
    FOREIGN KEY (planet_id) REFERENCES planets(id)
);

CREATE TABLE IF NOT EXISTS player_forge_cores (
    player_id INTEGER NOT NULL PRIMARY KEY,
    forge_cores INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (player_id) REFERENCES players(id)
);

CREATE INDEX IF NOT EXISTS idx_planet_shipyard_ascension_rank
    ON planet_shipyard_ascension(forge_rank);
```

PK is `planet_id` (single active campaign per shipyard, unlike Mine Evolution's composite `(planet_id, building_type)` since there's only one shipyard per planet).

---

## API

`POST /api/shipyard/forge-campaign/start` — begins a campaign for the next rank; snapshots `campaign_started_at`, zeroes `hull_mass_progress`.

`GET /api/shipyard/forge-campaign` — current pillar progress (server-computed only; no client math).

`POST /api/shipyard/forge-ascend` — atomic single-TX flow, same shape as Mine Evolution's evolve endpoint:

1. `finish_due_work`
2. Re-verify all 4 pillars complete
3. Spend Tribute (`try_spend_resources_conn`, planet-scoped) + consume committed Forge Cores
4. `forge_rank += 1`; `campaign_active = 0`
5. Commit

Guarantees: no rank increase without all 4 pillars; idempotent via `request_id` (`get_idempotent_action`/`save_idempotent_action`), matching Mine Evolution's pattern.

---

## UI

Shipyard planet view: Stellar Forge panel below the build queue once unlock condition is met. Campaign view shows 4 pillar progress bars + "Initiate Ascension" button (disabled until all 4 read complete). Server authority only.

---

## Ticket map

| Ticket | Focus | Status |
|---|---|---|
| GC-3000 | Master doc + EPICS.md / CORE_ARCHITECTURE.md §17 owner row | ✅ |
| GC-3001 | Migration `150_stellar_forge.sql` + `game/stellar_forge/` package + unlock-condition check (dynamic max-level read via `get_max_level_for_building`) | ✅ |
| GC-3002 | Pillar 1 — Tribute cost calc (trailing production via `EffectResolver.get_building_production_per_hour`) + planet-scoped 3-resource spend (`pay_tribute`) | ✅ |
| GC-3003 | Pillar 2 — Hull Mass counter wired into shipyard delivery path (`game/shipyard_queue.py:_finish_due_shipyard_jobs_impl`, next to `add_planet_ships`), category-mix validation (`manufacturing_trial_complete`) | ✅ |
| GC-3004 | Pillar 3 — Operational Trial hooks: Exploration + legendary-event Forge Core drop (`game/fleet.py` expedition completion), Salvage (`game/fleet.py` debris recycle), Warfare (`game/fleet.py` `_resolve_attack_arrival`), Logistics (`game/fleet.py` transport-to-own-planet), Titan (`game/world_boss.py` `execute_instant_attack`, instant-attack path only — the fleet-flight World Boss path is not yet wired) | ✅ (Titan: instant-attack path only) |
| GC-3005 | Pillar 4 — `player_forge_cores` wallet + `grant_forge_cores`; sourced from legendary expedition events (15% chance) and World Boss kills (50% chance) — no new drop-table engine | ✅ (Phase 1 sources only) |
| GC-3006 | `GET /api/shipyard/forge-campaign`, `POST /api/shipyard/forge-campaign/start`, `POST /api/shipyard/forge-tribute`, `POST /api/shipyard/forge-ascend` — atomic, idempotent (`request_id`) | ✅ |
| GC-3007 | Shipyard building-card panel (`templates/buildings.html`), click handlers (`static/main.js`), CSS, locale keys (8 languages), `tests/test_stellar_forge.py` | ✅ (no dedicated confirm modal — direct-action buttons, unlike Mine Evolution's modal flow) |

### Known Phase 1 gaps (tracked, not blocking)

- Rank rewards (extra queue slot, Nanite-Assisted order option) are computed by `formulas.queue_slot_bonus` / `nanite_assist_unlocked` but **not yet enforced** at the shipyard queue / order-placement layer — Phase 1 ships the campaign loop; wiring the reward payoff into `game/shipyard_queue.py` is a follow-up ticket.
- Titan Protocol only counts the instant-attack World Boss path (`execute_instant_attack`), not the fleet-flight arrival path (`resolve_attack_arrival`).
- Forge Specialization (Rank III unlock) is docs-only per the original Phase 2 scope.
