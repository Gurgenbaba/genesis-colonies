# Buildings System

Gebäude, Kosten, Requirements und Bau-Queue (v1.5.3).

Kanonischer Gebäude-Key für Werft: **`orbital_shipyard`** (Legacy-Alias `shipyard` wird beim Lesen gemappt).

---

## Gebäude-Keys

`BUILDING_ORDER` in `game/buildings.py`:

| Tab | Keys |
|-----|------|
| **resources** | `metal_mine`, `crystal_mine`, `solar_plant`, `fuel_cell_plant`, `metal_storage`, `crystal_storage` |
| **research** | `research_lab`, `academy` |
| **military** | `orbital_shipyard`, `defense_factory`, `barracks`, `radar_array` |
| **infrastructure** | `command_center`, `shield_generator`, `terraformer`, `nanofactory`, `geothermal_nexus`, `planet_core_nexus` |

`MAX_BUILDING_LEVEL = 50` (erweiterbar via `planet_core_nexus` / `geothermal_nexus` für Minen/Solar/Storage).

---

## Scope

- Levels: `planet_buildings` — **pro Planet**
- Queue: `build_queue.planet_id`
- UI/Actions: `get_context_planet()` ([PLANET_SCOPE.md](PLANET_SCOPE.md))

---

## Kosten & Zeit

**Kosten:** `BASE_COST[type] × COST_FACTOR^(target_level - 1)` → metal + crystal

**Zeit:** `BUILD_TIME_BASE × BUILD_TIME_FACTOR^(level-1)` ÷ EffectResolver `get_build_time_seconds()`

Modifier: `buildtime_tech`, `nanofactory`, `build_speed` (Settings).

---

## Requirements (Auszug)

| Gebäude | Voraussetzung |
|---------|---------------|
| `fuel_cell_plant` | solar_plant ≥1, crystal_mine ≥2 |
| `research_lab` | metal_mine ≥3, crystal_mine ≥2 |
| `orbital_shipyard` | command_center ≥2 |
| `terraformer` | command_center ≥4, storages ≥3, storage_tech ≥1 |
| `planet_core_nexus` | command_center ≥6, nanofactory ≥2, geothermal_nexus ≥1, storage_tech ≥3, energy_tech ≥4 |

Vollständige Map: `BUILDING_REQUIREMENTS` in `game/buildings.py`.

---

## Bau-Queue

| Eigenschaft | Wert |
|-------------|------|
| Tabelle | `build_queue` |
| Limit | `game_settings.queue_limit` (Default **3**, min 1) |
| Scheduling | Sequenziell: Start = max(now, letztes finish_time) |
| Zahlung | Sofort metal/crystal via `try_spend_resources_conn` |
| Finish | `queue_engine.finish_player_build_jobs` → Level++ |
| Cancel | Kein Refund |

Due-Finisher läuft vor jeder Mutation und in `refresh_player_live_state()`.

---

## APIs

| Route | Methode | Body |
|-------|---------|------|
| `/buildings` | GET | SSR-Seite |
| `/upgrade/<building_type>` | GET | Legacy redirect |
| `/api/buildings/upgrade` | POST | `{ building_type, request_id? }` |
| `/api/buildings/cancel` | POST | `{ job_id }` |

Antwort: `{ ok, reason, job?, state }` — immer frischer game-state.

---

## UI

- Template: `templates/buildings.html` — 4 Tabs
- Queue panel: `#build-queue-root` (JS aus Poll)
- Planet-Chip: active planet name
- Buttons: `.btn-upgrade` → intercepted → POST API

Panel-Daten: `get_buildings_panel_rows()` für SSR + Poll `buildings_panel`.

---

## EffectResolver

- Build time: `get_build_time_seconds()`
- Max level caps für Minen/Solar/Storage
- Storage capacity für Economy

Siehe [EFFECTS.md](EFFECTS.md).

---

## Neues Gebäude hinzufügen

1. Key in `BUILDING_KEYS` / `BUILDING_ORDER`
2. Spalte in `planet_buildings` (Baseline + Migration)
3. `BASE_COST`, `BUILD_TIME_*`, optional `BUILDING_REQUIREMENTS`
4. Template-Zeile in `buildings.html`
5. EffectResolver-Hooks falls nötig
6. pytest: Queue + Persistence

**Nicht:** Paralleles Gebäude-System oder zweite Queue-Tabelle.

---

## Tests

```bash
python -m pytest tests/test_race_conditions.py tests/test_game_state_live.py tests/test_effects.py -v -k "build"
```
