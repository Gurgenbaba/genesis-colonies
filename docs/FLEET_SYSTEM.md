# Fleet System

Flotten, Schiffe, Missionen und Tick (v1.5.3).

Kanonische Module: `game/fleet.py`, `game/fleet_calc.py`, `game/fleet_defs.py`, `game/fleet_api.py`, `game/expedition_events.py`.

**Kein zweites Fleet-State-System** — alle Bewegungen in `fleet_movements`.

---

## Schema (Migration 027, 032)

| Tabelle | Rolle |
|---------|-------|
| `planet_ships` | `(planet_id, ship_key, amount)` |
| `fleet_presets` | Gespeicherte Loadouts (`ships_json`, optional target/mission) |
| `fleet_batches` | Mass jobs (z. B. `mass_expedition`) |
| `fleet_movements` | Aktive/abgeschlossene Flüge |

**Movement statuses:** `outbound`, `holding`, `returning`, `completed` (+ `cancelled`, `failed` im CHECK)

**Missions:** `transport`, `collect`, `deploy`, `spy`, `attack`, `hold`, `expedition`, `colonize`

Gate: `fleet_schema_ready()` — Features degradieren gracefully ohne Migration.

---

## Schiffe

Definiert in `game/fleet_defs.py`:

- `ACTIVE_SHIP_KEYS` — im Fleet-UI sichtbar
- `build_cost`: metal, crystal, fuel_cells
- Legacy-Key-Aliases für alte Saves
- `eclipse_runner`: `phase2_only` — aus UI ausgeschlossen

Schiffsbau: [Shipyard](BUILDINGS_SYSTEM.md) → `orbital_shipyard` → `shipyard_queue` → Credit auf `planet_ships`.

---

## Planet Scope

| Operation | Origin |
|-----------|--------|
| Fleet page | `get_context_planet()` |
| `POST /api/fleet/send` | `origin_planet_id` im Body oder context |
| `GET /api/fleet/state` | `?planet_id=` oder context |
| Ship deduction | Origin planet `planet_ships` |

Flotten-Slots: `computer_tech` + Basis 1 (Fallback 3 wenn kein Research).

Overview zeigt **alle** Bewegungen des Spielers (nicht nur active planet).

---

## Flight Math (`fleet_calc.py`)

- Distanz aus Galaxy-Koordinaten ([GALAXY_SYSTEM.md](GALAXY_SYSTEM.md))
- Speed aus langsamstem Schiff + `EffectResolver.fleet_speed_multiplier`
- Fuel: `fuel_efficiency` Research + Schiff-defs
- Cargo capacity pro Schiffstyp

Preview: `POST /api/fleet/preview` → debounced im Client (~300ms).

---

## Missionen (Ankunft)

| Mission | Verhalten |
|---------|-----------|
| **transport** | Cargo an Ziel; Schiffe kehren leer zurück; Messages |
| **collect** | Eigene Kolonie: lädt Ressourcen bis Cargo-Cap (optional Abflug-Cargo); Ziel verliert Ressourcen; Rückflug; Origin erhält Fracht; Report |
| **deploy** | Schiffe + Ressourcen bleiben; movement completed |
| **spy** | Tiered probe intel (resources → fleet → buildings → activity); structured inbox report; Schiffe return |
| **attack** | **Placeholder** — „combat not active“; Schiffe return |
| **hold** | `holding` für 3600s, dann return (ally only wenn Alliance-Schema) |
| **expedition** | Event engine (`expedition_events.py`): weighted outcomes, loot cap = expedition-hull cargo × 50, optional delay; inbox event-card report (GC-402C) |

### Expedition (GC-402 / 402B / 402C)

| Ticket | Backend / UI | Module |
|--------|----------------|--------|
| **GC-402** | Weighted event roll on arrival; `report_version: 2` metadata | `game/expedition_events.py`, `game/fleet.py` |
| **GC-402B** | Fleet send preview: mission hints, ok/blocked status, expedition auto-position 16 | `static/main.js`, `templates/fleet.html` |
| **GC-402C** | Inbox debrief: event card, risk/find meta, loot chips, theme colors per event type | `static/js/messages.js`, `static/style.css` |

Event keys: `void_scan`, `mineral_deposit`, `fuel_cache`, `debris_salvage`, `nav_interference`, `distress_beacon`, `sensor_glitch`, `ancient_stash`. Roll ist deterministisch pro `movement_id`.
| **colonize** | `colonize_planet()`; verbraucht `seed_ark` |

Logistics bulk API (`collect_resources` / `distribute_resources`): weiterhin `logistics_not_implemented` (Phase 2). Einzel-Collect über Fleet-Send-Mission `collect`.

---

## Tick

`process_fleet_tick(player_id)`:

- Ankünfte verarbeiten
- Hold-Ende → return
- Returns abschließen

Aufgerufen von:

- `GET /api/fleet/state`
- `queue_engine.finish_due_work()` (fleet_arrivals / fleet_returns counts)
- Client countdown expiry → refresh

---

## APIs

| Route | Methode | Zweck |
|-------|---------|-------|
| `/fleet` | GET | SSR page |
| `/api/fleet/preview` | POST | Send preview |
| `/api/fleet/resolve-target` | GET/POST | Target type validation |
| `/api/fleet/state` | GET | Live ships + movements |
| `/api/fleet/send` | POST | Send fleet |
| `/api/fleet/presets` | GET/POST | List/create presets |
| `/api/fleet/presets/<id>` | PUT/PATCH/DELETE | CRUD |
| `/api/fleet/mass-expedition` | POST | Wave expeditions |
| `/api/fleet/logistics/*` | POST | Not implemented |
| `/api/fleet/dev/seed-ships` | POST | Debug seed |

Response envelope: `{ ok, error, message_key, data }` via `fleet_api.py`.

---

## Frontend (`static/main.js`)

- Module: `GC.modules.fleet` → `initFleet()`
- Forms: `data-no-pjax` (fetch-only send)
- `refreshFleetState()` on init, after actions, countdown zero
- Realigns `planet_id` from `GC.lastState.active_planet_id`
- Galaxy prefill: `applyFleetUrlPrefill()` from query params
- **GC-402B:** Mission feedback panel (`data-fleet-mission-feedback`), preview status `is-ok` / `is-blocked`, expedition → position 16

Template: `templates/fleet.html` — embedded JSON state, `#fleet-page[data-planet-id]`.

Inbox expedition reports: `static/js/messages.js` → `renderExpeditionReport()` (GC-402C event cards).

---

## Abhängigkeiten

| System | Nutzung |
|--------|---------|
| Galaxy | Koordinaten, target resolution |
| Planet Evolution | `colonize_planet` |
| Alliance | `are_players_allied`, hold mission |
| Research | slots, fuel_efficiency |
| Messages | transport, spy, combat, expedition notifications |
| Shipyard | `planet_ships` supply |

---

## Placeholder / Phase 2

- Combat resolver (attack)
- Logistics bulk collect/distribute API
- Recycler mission (`harvest_reclaimer` def only)
- `fleet_presets.mission_type` CHECK fehlt `colonize` (nur movements migriert in 032)

---

## Tests

```bash
python -m pytest tests/test_fleet.py tests/test_shipyard.py tests/test_galaxy.py -v
```
