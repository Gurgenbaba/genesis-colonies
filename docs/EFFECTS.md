# Effect System — Genesis Colonies

Authoritative gameplay math: production in `game/production_formula.py` ([PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md)); energy, storage, build/research time in `game/effects/effect_resolver.py`.  
Consumers (`resources`, `buildings`, `research`) delegate to these modules; the frontend must not replicate formulas.

## Status overview

| Area | Status | Notes |
|------|--------|--------|
| Economy (production, energy, storage) | **Fixed** | Applied on every resource tick / derived sync; includes galactic directives + diplomacy (GC-720E, GC-721H) |
| Time (build, research, lab, academy, nanofactory) | **Fixed** | `get_build_time_seconds` → `power_build_seconds` (GC-850A); `get_research_time_seconds` |
| Building caps (core nexus, geothermal) | **Fixed** | Max levels for mines/solar/fuel/storage; terraform = storage bonus only |
| Combat (`weapon_tech`, `armor_tech`, `shield_tech`) | **Fixed** | Applied in `simulate_battle()` via `EffectResolver.get_combat_modifiers()` — [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Fleet (`navigation_tech`, `engine_tech`, `fuel_efficiency`) | **Fixed** | `fleet_speed_multiplier`, `fuel_efficiency_factor` — consumed in `fleet.py` / `fleet_calc.py` |
| Radar (`radar_array` → `scan_range`) | **Not wired** | **No scan/galaxy engine** |
| Multi-universe | **Not supported** | Single SQLite DB; `universe_name` is display config only — **no `universe_id` in schema** |

## Developer note — prepared modifiers

Prepared modifiers may appear in:

- Admin debug: `GET /api/admin/player/<id>/effects` (`modifiers_prepared`, `sources_prepared`)
- Future UI tooltips / tech tree “planned” hints

Combat and fleet modifiers are **active** where documented in [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) and [FLEET_SYSTEM.md](FLEET_SYSTEM.md). Only `scan_range` remains prepared until a scan engine consumes it.

Build time: `get_build_time_seconds()` delegates to `economy_balance.power_build_seconds()` before player/admin speed modifiers (GC-850A).

### Build duration (`get_build_time_seconds`)

```text
seconds = power_build_seconds(building, level) / effective_speed
return max(int(seconds), 1)   # 1-second floor (GC-858)
```

**`effective_speed`** stacks multiplicatively:

1. `buildtime_tech` → `build_time_speed × (1 / 0.97^level)`
2. Galactic directives / diplomacy → `build_time_speed` (whitelist)
3. `nanofactory` → duration `× 0.70^level` (applied as ÷ in player speed)
4. `command_center` → duration `× 0.75^level` for **nanofactory upgrades only**
5. Admin/universe `build_speed` setting

**UI note (GC-858):** Nanofactory card shows flat `level × 30 %` for display; runtime uses `0.70^level`. Production milestones (`+N %`) are **output** previews, not build-speed bonuses. See [GC-858_BUILD_TIME_MODIFIER_AUDIT.md](GC-858_BUILD_TIME_MODIFIER_AUDIT.md).

### Galactic directives (GC-720E / GC-720E2)

`EffectResolver` loads merged directive mechanics via `get_galaxy_directive_mechanics(planet.galaxy)` — no per-consumer `if directive` branches.

**EffectResolver keys:** economy/time (GC-720E); combat additive bonuses; fleet multipliers; `shipyard_time_speed` / `defense_time_speed`.

**Expedition flags:** `get_directive_flags_for_galaxy()` → `expedition_events.resolve_expedition_outcome()`.

**Still deferred:** colonize/trader/command-map unlock flags, `expedition_slot_bonus`, `expedition_legendary_bonus`.

Owner: `game/galactic_directives/` · [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md)

### Galactic diplomacy (GC-721G / GC-721H)

After buildings/research/planet mechanics and **galactic directives**, `EffectResolver` applies merged diplomacy mechanics via `get_galaxy_diplomacy_mechanics(planet.galaxy)` (personality → resolution → emergency bundle from GC-721G).

**Merge order in `get_modifiers()`:** Research/Buildings → Galactic Directives → Galactic Diplomacy.

**Keys:** same `GD_EFFECT_RESOLVER_ACTIVE_KEYS` whitelist as directives (`extract_active_effect_resolver_modifiers`); additive keys (`weapon_bonus`, `armor_bonus`, `shield_bonus`) sum, multiplicative keys multiply onto the directive-adjusted base.

**Source labels:** `gdp:<personality_key>+<resolution_key>+<emergency_key>` (omitted segments when inactive).

Owner: `game/galactic_diplomacy/` · [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md)

### Alliance technologies (EPIC-09)

After inventory boosters, `EffectResolver` applies alliance tech modifiers via `get_alliance_effect_modifiers(player_id)` — **members only**.

**Merge order:** Research/Buildings → Galactic Directives → Galactic Diplomacy → Inventory Boosters → **Alliance**.

**Keys:** `research_time_speed`, production factors, `armor_bonus`, `shield_bonus`. Expedition loot uses `expedition_loot_mult` in `fleet.py` directive flags (not ER keys).

Owner: `game/alliance.py` · [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md)

Use labels like **“prepared / not active”** in admin copy when showing `scan_range` and other deferred flags.

## Offline queue finish → derived state

```
queue_engine.finish_due_work()
  → sync_derived_state_after_queue_finish()
    → update_planet_resources(..., skip_queue_finish=True)
```

`skip_queue_finish=True` guarantees **no second** `finish_due_work_once` pass (no recursion / double job processing).

Admin/cron tick responses include `derived_sync_count` (planets whose energy/production row was refreshed).

## Live UI refresh (`/api/game-state`)

Pipeline (single request, one finish pass):

1. `refresh_player_live_state()` → `finish_due_work_once` + `sync_derived_state` + `update_planet_resources(skip_queue_finish=True)`
2. `get_build_queue_status(skip_finish=True)` / `get_research_status(skip_finish=True)` — read-only queue/research
3. Payload includes `energy`, `overview.rows`, `production_per_hour`
4. `static/main.js` `applyGameStateData()` updates resource bar + overview table without reload

### `energy_tech` (mine consumption only)

- **Effect:** reduces **mine** energy draw only (`metal_mine` / `crystal_mine`), not solar output or other buildings.
- **Formula:** `mine_energy_factor = max(0, 1 − 0.05 × level)` for display/modifiers. Actual per-consumer draw: `max(1, int(raw × max(0.01, mine_energy_factor)))`. Display reduction % is linear and unbounded; gameplay draw never reaches 0 for active mines/plants.
- **Not:** a flat reduction of total colony power draw from solar/command center/etc.
- **UI:** `energy.used`, `energy.efficiency_pct`, overview energy hint class update on poll (no reload).

### Call order (no double finish)

1. `refresh_player_live_state()` once per request (sets Flask `g.gc_live_state_refreshed`).
2. `get_build_queue_status(skip_finish=True)` / `get_research_status(skip_finish=True)` — read-only.
3. If `skip_finish=False` is passed after step 1, `coerce_skip_finish()` forces `True` automatically.

Worker/admin ticks use `finish_due_work()` → `sync_derived_state` (no HTTP guard needed).

## Tests

- `tests/test_effects.py` — unit/integration (economy, guards, offline sync, live pipeline)
- `tests/test_game_state_live.py` — Flask `/api/game-state` after research finish
- `tests/test_queue_engine.py` — 14 tests (queue finish, dedup, tick runner)

Run: `python -m pytest tests/test_effects.py tests/test_game_state_live.py tests/test_queue_engine.py -v`

### Manual browser check (no reload)

1. Open Overview, queue `energy_tech` (or any due research), wait for timer end.
2. Confirm **no full page reload**; resource bar + overview mine table update on poll.
3. DevTools → Network: `GET /api/game-state` after finish shows lower `energy.used` (for `energy_tech`) and updated `overview.rows[].production_per_hour`.
4. Energy hint CSS class (`overview-energy-ok` / `low` / `zero`) changes without navigation.

`static/main.js` `patchOverviewTable` / `patchOverviewEnergyHint` no-op when the overview partial is not in the DOM (PJAX on other pages); next poll on Overview patches cleanly.
