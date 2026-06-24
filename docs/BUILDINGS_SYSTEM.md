# Buildings System

Gebäude, Kosten, Requirements und Bau-Queue.  
**Stand:** v1.5.9.x · Kosten/ROI: [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

Kanonischer Gebäude-Key für Werft: **`orbital_shipyard`** (Legacy-Alias `shipyard` wird beim Lesen gemappt).

---

## Gebäude-Keys

`BUILDING_ORDER` in `game/buildings.py`:

| Tab | Keys |
|-----|------|
| **resources** | `metal_mine`, `crystal_mine`, `solar_plant`, `fuel_cell_plant`, `metal_storage`, `crystal_storage`, `fuel_storage` |
| **research** | `research_lab`, `academy` |
| **military** | `orbital_shipyard`, `defense_factory`, `barracks`, `radar_array` |
| **infrastructure** | `command_center`, `shield_generator`, `terraformer`, `nanofactory`, `geothermal_nexus`, `planet_core_nexus` |

`MAX_BUILDING_LEVEL = 50` (Basis). **L51+** nur über Nexus (GC-821 Endgame-Gate):

| Gebäude | Cap-Formel |
|---------|------------|
| `metal_mine`, `crystal_mine`, `solar_plant`, `fuel_cell_plant` | `50 + planet_core_nexus + 2×geothermal_nexus` |
| `metal_storage`, `crystal_storage`, `fuel_storage` | `50 + 2×geothermal_nexus` (ohne Core) |
| alle übrigen | `50` |

`terraformer`: +5 % Lagerkapazität/Stufe — **kein** Gebäude-Level-Cap. Owner: `EffectResolver.get_max_building_level()`.

Queue-Cancel-Refunds: [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) (GC-831).

---

## Scope

- Levels: `planet_buildings` — **pro Planet**
- Queue: `build_queue.planet_id`
- UI/Actions: `get_context_planet()` ([PLANET_SCOPE.md](PLANET_SCOPE.md))

---

## Kosten & Zeit

### Upgrade-Kosten (live)

**Kosten:** `economy_balance.power_upgrade_cost()` via `get_upgrade_cost()` — Power-Kurven + Minen-ROI-Anker (GC-821 / GC-821F).

Legacy `BASE_COST × COST_FACTOR^(level-1)` nur noch Audit/Tests — **nicht** der Live-Pfad.

### Build-Zeit (live, GC-850A)

`EffectResolver.get_build_time_seconds()` → `power_build_seconds()` ÷ Speed-Boni (`build_speed`, `buildtime_tech`, `nanofactory`, …).

---

## Requirements (Auszug)

| Gebäude | Voraussetzung |
|---------|---------------|
| `fuel_cell_plant` | solar_plant ≥1, crystal_mine ≥2 |
| `fuel_storage` | fuel_cell_plant ≥4 |
| `research_lab` | metal_mine ≥3, crystal_mine ≥2 |
| `academy` | research_lab ≥2 |
| `orbital_shipyard` | command_center ≥2 |
| `defense_factory` | orbital_shipyard ≥2 |
| `terraformer` | command_center ≥4, storages ≥3, storage_tech ≥1 |
| `planet_core_nexus` | command_center ≥6, nanofactory ≥2, geothermal_nexus ≥1, storage_tech ≥3, energy_tech ≥4 |

Vollständige Map: `BUILDING_REQUIREMENTS` in `game/buildings.py`.

---

## Bau-Queue

| Eigenschaft | Wert |
|-------------|------|
| Tabelle | `build_queue` |
| Limit | `game_settings.queue_limit` (Default **5**, Code-Fallback **3** wenn Setting fehlt) |
| Scheduling | Sequenziell; nach Cancel/Enqueue: `recalculate_build_queue_finish_times()` |
| Zahlung | Sofort metal/crystal via `try_spend_resources_conn`; Kosten-Snapshot auf Row (Migration 076) |
| Finish | `queue_engine.finish_player_build_jobs` → Level++ |
| Cancel | **GC-831 Refund** (100 % pending / 50 % active); Restqueue neu terminiert |

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
- **Queue-UX (GC-536B / GC-644C):** Kompakt-Header `#build-queue-compact` + Card-Queues pro Gebäude
- **Kein globaler Queue-HUD** unter der Ressourcenleiste
- Buttons: `.btn-upgrade` → intercepted → POST API
- Card-Queue: `GC.renderCardQueueBlock` / `.gc-card-queue-block` (Timer + Progress aus Poll)

Panel-Daten: `get_buildings_panel_rows()` für SSR + Poll `buildings_panel` (inkl. optional `queue_job` pro Row).

---

## EffectResolver

- Build time: `get_build_time_seconds()` → `power_build_seconds` (GC-821 / GC-850A)
- Max level caps für Minen/Solar/Storage
- Storage capacity für Economy

Siehe [EFFECTS.md](EFFECTS.md).

---

## Neues Gebäude hinzufügen

1. Key in `BUILDING_KEYS` / `BUILDING_ORDER`
2. Spalte in `planet_buildings` (Baseline + Migration)
3. `BUILDING_UPGRADE_CURVES` / `BUILD_TIME_CURVES` in `economy_balance.py` (+ Legacy `BASE_COST` für Audit)
4. Template-Zeile in `buildings.html`
5. EffectResolver-Hooks falls nötig
6. pytest: Queue + Persistence

**Nicht:** Paralleles Gebäude-System oder zweite Queue-Tabelle.

---

## Tests

```bash
python -m pytest tests/test_race_conditions.py tests/test_game_state_live.py tests/test_effects.py tests/test_gc821_economy_rebalance.py tests/test_gc831_queue_refund.py -v -k "build"
```
