# Effect System — Genesis Colonies

Authoritative gameplay math: production in `game/production_formula.py` ([PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md)); energy, storage, build/research time in `game/effects/effect_resolver.py`.  
Consumers (`resources`, `buildings`, `research`) delegate to these modules; the frontend must not replicate formulas.

## Status overview

| Area | Status | Notes |
|------|--------|--------|
| Economy (production, energy, storage) | **Fixed** | Applied on every resource tick / derived sync; includes galactic directives + diplomacy (GC-720E, GC-721H) |
| Time (build, research, lab, academy, nanofactory) | **Fixed** | `get_build_time_seconds` → `power_build_seconds` (GC-850A); `get_research_time_seconds` |
| Building caps (core nexus, geothermal) | **Fixed** | production mines are Nexus-limited up to L200, then Mine Ascension owns further +25-level gates ([MINE_EVOLUTION.md](MINE_EVOLUTION.md)); nexus still raises solar/storage caps; terraform = storage bonus only |
| Combat (`weapon_tech`, `armor_tech`, `shield_tech`) | **Fixed** | Applied in `simulate_battle()` via `EffectResolver.get_combat_modifiers()` — [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Fleet (`navigation_tech`, `engine_tech`, `fuel_efficiency`) | **Fixed** | `fleet_speed_multiplier`, `fuel_efficiency_factor`, `cargo_multiplier` — consumed in `fleet.py` / `fleet_calc.py` (incl. Commander Class) |
| Radar (`radar_array` → `scan_range`) | **Active** | Deep-Space Threat Net — passive fleet contacts via `build_radar_contacts` / `fleet_alerts` |
| Barracks (`barracks` → `shipyard_time_speed` + troop capacity) | **Active** | +2% shipyard speed/level; troop stock slots via `barracks_troop_capacity` — [VAULT_RAID_SYSTEM.md](VAULT_RAID_SYSTEM.md) |
| Shield generator (`shield_generator` → `shield_bonus`) | **Active** | +2% combat shield per level in `EffectResolver.get_combat_modifiers()` |
| Multi-universe | **Not supported** | Single SQLite DB; `universe_name` is display config only — **no `universe_id` in schema** |

## Developer note — prepared modifiers

Prepared modifiers may appear in:

- Admin debug: `GET /api/admin/player/<id>/effects` (`modifiers_prepared`, `sources_prepared`)
- Future UI tooltips / tech tree “planned” hints

Combat and fleet modifiers are **active** where documented in [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) and [FLEET_SYSTEM.md](FLEET_SYSTEM.md). `scan_range` drives the Deep-Space Threat Net (`game/fleet.py` → `build_radar_contacts`). Barracks contributes to `shipyard_time_speed` (+2%/level) and planetary troop capacity; shield generator adds to `shield_bonus` (+2%/level).

Build time: `get_build_time_seconds()` delegates to `economy_balance.power_build_seconds()` before player/admin speed modifiers (GC-850A).

`get_effect_resolver` reuses a **request-scoped** instance when player/planet/buildings/research fingerprints match (**GC-PERF-EFFECT-CACHE-001**). `force_refresh=True` bypasses the cache read; `clear_effect_resolver_cache` clears entries. No process TTL (stale energy risk).

### Build duration (`get_build_time_seconds`)

```text
seconds = power_build_seconds(building, level) / effective_speed
return max(int(seconds), 1)   # 1-second floor (GC-858)
```

**`effective_speed`** stacks multiplicatively:

1. `buildtime_tech` → duration `× 0.985^level` (applied as ÷ in `build_time_speed`)
2. Galactic directives / diplomacy → `build_time_speed` (whitelist)
3. `nanofactory` → build speed `1 + 0.55 × level^0.8` (duration ÷ speed; diminishing returns)
4. `command_center` → duration `× 0.75^level` for **nanofactory upgrades only**
5. Admin/universe `build_speed` setting

**UI (GC-NANO-BUILDTIME-AUDIT-001):** Nanofactory tech card shows server preview (speed × current/next, reference build seconds, cumulative vs marginal savings) — no frontend formula. Production milestones (`+N %`) are **output** previews, not build-speed bonuses. Historical audit notes: [GC-858_BUILD_TIME_MODIFIER_AUDIT.md](GC-858_BUILD_TIME_MODIFIER_AUDIT.md).

### Galactic directives (GC-720E / GC-720E2)

`EffectResolver` loads merged directive mechanics via `get_galaxy_directive_mechanics(planet.galaxy)` — no per-consumer `if directive` branches.

**EffectResolver keys:** economy/time (GC-720E); combat additive bonuses; fleet multipliers; `shipyard_time_speed` / `defense_time_speed`.

**Expedition flags:** `get_directive_flags_for_galaxy()` → `expedition_events.resolve_expedition_outcome()`.

**Wired domain flags (GC-720J):** `max_colonies_bonus` / `colonize_cost_mult` (expansion + seed_ark cost), `trader_daily_limit_mult`, `scrapyard_yield_mult`, `defense_combat_mult` (defender defense units), `queue_limits.research` via `get_directive_queue_limit_bonus`, `planet_xp_mult` (+ optional cap).

**Still deferred:** `unlock:world:*` / `unlock:expansion_site:*`, `trade_route_speed_mult`.

**Wired expedition flags:** `expedition_loot_mult`, `expedition_event_bonus`, `expedition_wreckage_bonus`, `expedition_event_factor`, `expedition_legendary_bonus` (weight boost in `_pick_event_key`), `expedition_slot_bonus` (extra fleet slots via `get_max_fleet_slots`).

Owner: `game/galactic_directives/` · [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md)

### Galactic diplomacy (GC-721G / GC-721H)

After buildings/research/planet mechanics and **galactic directives**, `EffectResolver` applies merged diplomacy mechanics via `get_galaxy_diplomacy_mechanics(planet.galaxy)` (personality → resolution → emergency bundle from GC-721G).

**Merge order in `get_modifiers()`:** Research/Buildings → Galactic Directives → Galactic Diplomacy.

**Keys:** same `GD_EFFECT_RESOLVER_ACTIVE_KEYS` whitelist as directives (`extract_active_effect_resolver_modifiers`); additive keys (`weapon_bonus`, `armor_bonus`, `shield_bonus`) sum, multiplicative keys multiply onto the directive-adjusted base.

**Source labels:** `gdp:<personality_key>+<resolution_key>+<emergency_key>` (omitted segments when inactive).

Owner: `game/galactic_diplomacy/` · [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md)

### Alliance technologies (EPIC-09)

After inventory boosters, `EffectResolver` applies alliance tech modifiers via `get_alliance_effect_modifiers(player_id)` — **members only**.

**Merge order:** Research/Buildings → Galactic Directives → Galactic Diplomacy → Inventory Boosters → Alliance → **Commander Class**.

**Keys:** `research_time_speed`, production factors, `armor_bonus`, `shield_bonus`. Expedition: `expedition_loot_mult` and `expedition_event_bonus` via `get_alliance_effect_modifiers()` in `fleet.py` directive flags (not ER keys). Handelskoordination: pool cap % and project duration via `trade_coord_bonus_pct()` in `alliance_catalog.py` (alliance-level, not per-player ER).

Owner: `game/alliance.py` · [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md)

### Commander Classes (EPIC-27)

After alliance, `EffectResolver` applies account class skill modifiers via `get_commander_effect_modifiers(player_id)`.

**Merge order:** … → Alliance → **Commander Class**.

**Keys:** class-dependent subset of active ER keys (`weapon/armor/shield_bonus`, prod factors, build/research/shipyard time speeds, fleet/cargo/fuel, `storage_factor`) plus prepared `scan_range` for Envoy.

**Source labels:** `class:<class_key>:<skill_key>`.

Owner: `game/commander_classes.py` · [COMMANDER_CLASSES.md](COMMANDER_CLASSES.md)

### Server Events (timed LiveOps)

Global timed bonuses from `game/server_events.py` (Admin LiveOps → Events).

**Production:** `production_context_from_resolver` sets `ProductionContext.event_modifier` from active `production_mult` factors (product of concurrent events). Multiplies **after** `directive_modifier` / ER overlay (research, GD, diplomacy, inventory boosters, alliance, class) — stacks with boosters as advertised.

**Expedition hold:** `fleet.expedition_stay_seconds` multiplies base stay by active `expedition_hold_mult` (e.g. `0.75` = −25%). `fleet_calc` uses the same helper for home-ETA.

**Build / research time:** `EffectResolver.get_modifiers` multiplies `build_time_speed` / `research_time_speed` by active server-event factors **after** inventory boosters, alliance, and commander class (single duration math owner).

**Shop discount:** `shop_discount_bps` is applied in `shop._resolve_cart_discount` (EUR premium shop). See [PAYMENT_SHOP.md](PAYMENT_SHOP.md) / [SERVER_EVENTS.md](SERVER_EVENTS.md).

**World cadence:** `asteroid_spawn_mult` / `world_boss_spawn_mult` / `inactive_farm_mult` are read by their domain owners (`asteroids`, `world_boss`, `inactive_autoplay`) — no parallel spawn formulas.

Use labels like **“prepared / not active”** in admin copy only for modifiers still in `PREPARED_MODIFIER_KEYS` (currently empty — `scan_range` is live).

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

### Effective Stat Display (GC-EFFSTAT)

Wherever catalog stats are shown to players (ship/defense cards, ship detail Speed/Cargo/Fuel, fleet pick tooltips, fleet preview, Battle Lab combat cards), the UI must show:

1. **Primary:** effective gameplay value (EffectResolver full stack when `player_id`+`conn` available)
2. **Secondary:** single net total bonus `%` (`bonus_pct` / `bonus_display`) — omit when `0`
3. **Detail:** source breakdown via `active_bonuses` / `sources`

Owner: `game/technical_data.py` → `build_effective_stat`, `resolve_unit_effect_context`, `build_unit_technical_block`. Shared macro: `templates/partials/effective_stat.html`. No frontend formulas.

### `energy_tech` (mine consumption only)

- **Effect:** reduces **mine** energy draw only (`metal_mine` / `crystal_mine`), not solar output or other buildings.
- **Formula:** `mine_energy_factor = max(0, 1 − 0.01 × level)` for display/modifiers. Actual per-consumer draw: `max(1, int(raw × max(0.01, mine_energy_factor)))`. Display reduction % is linear and unbounded; gameplay draw never reaches 0 for active mines/plants.
- **Alpha principle:** energy research improves mines but must not make power plants obsolete in the late game.

### `buildtime_tech` (build + research duration)

- **Formula:** duration × `0.985 ** level` (~1.5 % faster per level, multiplicative). Stacks with nanofactory, lab, academy — does not replace nanofactory investment.

### `nanofactory` (building build duration)

- **Role:** shortens build time of **other buildings** (and also its own upgrade — same duration multiplier path). Does **not** use Command Center.
- **Formula (canonical):** `speed_nano = 1 + 0.55 × level^0.8`, then `duration /= speed_nano`. Owner: `EffectResolver.nanofactory_build_speed` / `get_build_time_seconds`.
- **Marginal next level:** `duration_next ≈ duration_current × (speed_cur / speed_next)` — at high levels ~2–3 % (e.g. Nano 25→26), not a flat −25 % of the displayed time.
- **Not:** obsolete exponential nano collapse (`0.70^level` / player expectation “−25 % per nano level on current time”).
- **UI:** Tech-card preview from `build_nanofactory_time_preview()` uses reference **`metal_mine`** (never mixes Command Center into that example). Shows speed × current/next, cumulative vs L0, and marginal next-level seconds.
- Upgrade costs: see [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) / `nanofactory_upgrade_cost`.

### `command_center` (nanofactory upgrade duration only)

- **Role:** shortens **only** the build time of the **nanofactory** building (`duration × 0.75^cc_level`).
- **Never** applied to mines, labs, yards, or other normal buildings — Command Center must not appear in their nano preview.
- UI flat “×15 %” on the CC card is a separate display helper; runtime for nano upgrades is `0.75^level`.

### `radar_array` (Deep-Space Threat Net)

- **Effect:** `scan_range += 2 × level` — passive Threat Net contacts (Sensorphalanx-style Fleet-HUD rows + Galaxy Radar tab list: mission/route/ETA from tier 1).
- **Owner:** `EffectResolver` → `build_radar_contacts` / HUD + Galaxy Radar tab. Galaxy **ring** fleet markers remain deferred.

### `barracks` (shipyard speed + ground troops)

- **Shipyard:** `shipyard_time_speed *= 1 + 0.02 × level`.
- **Troops:** stock capacity `barracks_troop_capacity(level)` — see [VAULT_RAID_SYSTEM.md](VAULT_RAID_SYSTEM.md). Training UI: Defense page tab Bodentruppen.

### `shield_generator` (combat shield)

- **Effect:** `shield_bonus += 0.02 × level` in combat modifiers (same additive stack as `shield_tech` / directives).

### `storage_tech` and depot capacity

- **Depot base:** `storage_capacity_at_depot_level(level)` = `150_000 + 24h × mine_output("metal", level × 3)` before storage tech / terraformer.
- **Tech formula:** additive linear multiplier, `capacity *= (1 + storage_tech_level × 0.15)`.
- **Also stacks with:** Terraformer (+5 % storage capacity per level) and external `storage_factor` modifiers.
- **Not:** production-anchor jumps at L1, frontend math, or a second storage curve.

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
