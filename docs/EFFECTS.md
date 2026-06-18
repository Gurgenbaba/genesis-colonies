# Effect System — Genesis Colonies

Authoritative gameplay math lives in `game/effects/effect_resolver.py`.  
Consumers (`resources`, `buildings`, `research`) delegate to `EffectResolver`; the frontend must not replicate formulas.

## Status overview

| Area | Status | Notes |
|------|--------|--------|
| Economy (production, energy, storage) | **Fixed** | Applied on every resource tick / derived sync; includes galactic directives (GC-720E) |
| Time (build, research, lab, academy, nanofactory) | **Fixed** | `get_build_time_seconds`, `get_research_time_seconds` |
| Building caps (core nexus, geothermal, terraform) | **Fixed** | Max levels, storage, solar bonus |
| Combat (`weapon_tech`, `armor_tech`, `shield_tech`) | **Fixed** | Applied in `simulate_battle()` via `EffectResolver.get_combat_modifiers()` — [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Fleet (`navigation_tech`, `engine_tech`) | **Prepared only** | Modifiers computed; **no fleet engine** |
| Radar (`radar_array` → `scan_range`) | **Prepared only** | **No scan/galaxy engine** |
| Multi-universe | **Not supported** | Single SQLite DB; `universe_name` is display config only — **no `universe_id` in schema** |

## Developer note — prepared modifiers

Prepared modifiers may appear in:

- Admin debug: `GET /api/admin/player/<id>/effects` (`modifiers_prepared`, `sources_prepared`)
- Future UI tooltips / tech tree “planned” hints

Combat and fleet modifiers are **active** where documented in [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) and [FLEET_SYSTEM.md](FLEET_SYSTEM.md). Radar (`scan_range`) remains prepared until a scan engine consumes it.

### Galactic directives (GC-720E)

`EffectResolver` loads merged directive mechanics via `get_galaxy_directive_mechanics(planet.galaxy)` — no per-consumer `if directive` branches.

**Active in EffectResolver (phase 1):** `metal_prod_factor`, `crystal_prod_factor`, `fuel_prod_factor`, `mine_energy_factor`, `solar_output_factor`, `storage_factor`, `build_time_speed`, `research_time_speed`.

**Deferred (GC-720E2+):** fleet, combat, expedition, command-map flags — present in directive JSON but ignored by `EffectResolver` until wired.

Owner: `game/galactic_directives/` · [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md)

Use labels like **“prepared / not active”** in admin copy when showing `weapon_bonus`, `scan_range`, etc.

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
