# Fleet System

Flotten, Schiffe, Missionen und Tick (v1.5.4).

Kanonische Module: `game/fleet.py`, `game/fleet_calc.py`, `game/fleet_defs.py`, `game/fleet_api.py`, `game/fleet_target.py`, `game/expedition_events.py`.

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

**Missions:** `transport`, `collect`, `deploy`, `spy`, `attack`, `hold`, `expedition`, `colonize`, `recycle`

Gate: `fleet_schema_ready()` — Features degradieren gracefully ohne Migration.

---

## Schiffe

Definiert in `game/fleet_defs.py`:

- `ACTIVE_SHIP_KEYS` — im Fleet-UI sichtbar
- `build_cost`: metal, crystal, fuel_cells
- Legacy-Key-Aliases für alte Saves
- `eclipse_runner`: `phase2_only` — aus UI ausgeschlossen

Schiffsbau: [Shipyard](BUILDINGS_SYSTEM.md) → `orbital_shipyard` → `shipyard_queue` → Credit auf `planet_ships`.

### Shipyard — Einheiten-Bauzeit (GC-852)

**Owner:** `game/shipyard.py` — **nicht** `EffectResolver` / `power_build_seconds`.

Das **Gebäude-Upgrade** `orbital_shipyard` nutzt die normale Gebäude-Bauzeit ([BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md)).  
Die **Schiffsbau-Zeit pro Einheit** in der Werft-Queue ist ein separates System.

| Eingabe | Quelle |
|---------|--------|
| Basiszeit pro Schiff | `fleet_defs.SHIPS[ship_key].build_seconds` |
| Werft-Stufe | `max(orbital_shipyard, shipyard)` auf dem Planeten (min. 1 wenn Werft existiert) |
| Universum-Speed | `game_settings.shipyard_speed` (Default 1.0, clamp 0.1–10) |
| Direktiven-Bonus | `EffectResolver` / Galactic Directives → `shipyard_time_speed` (pro Planet) |

**Formel (eine Einheit, ein Produktionszyklus):**

```text
unit_seconds = ceil(
  build_seconds × 0.9^(yard_level − 1)
  ÷ shipyard_speed
  ÷ shipyard_time_speed
)
```

Konstante: `BUILD_TIME_LEVEL_FACTOR = 0.90` (−10 % pro Werft-Stufe über 1).  
Ergebnis: `max(1, …)` Sekunden — Funktionen `unit_build_seconds()` / `_effective_build_seconds()`.

**Progressive Lieferung (Mehrfachauftrag):**

| Konzept | Formel / Owner |
|---------|----------------|
| Yard-Kapazität pro Zyklus | `3^yard_level` Einheiten-Slots (`orbital_production_batch_capacity`) |
| Gewicht pro Schiffstyp | `ceil(build_seconds / 5)` (`unit_production_weight`) |
| Effektive Batch-Größe | `max(1, yard_capacity // weight)` |
| Auftragsdauer | `ceil(amount / batch_capacity) × unit_seconds` (`production_job_duration_seconds`) |

Beispiel Speed ×1, Werft L1, `mule_courier` (`build_seconds = 120`):  
`unit_seconds = 120`, effektive Batch-Größe = 1 (Gewicht `ceil(120/5) = 24` > Yard-Kapazität 3) → Auftrag über 10 Schiffe = `10 × 120 = 1200 s`.

Kosten: `fleet_defs.build_cost` — **kein** Level-Multiplier (metal/crystal/fuel_cells direkt aus Def).

Cancel-Refund: `shipyard_queue` → `queue_refund.refund_from_stored_costs` (GC-831).

Analoges Muster für Verteidigung: [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) (`defense_factory`-Stufe, `defense_time_speed`).

**Queue-UX (GC-536D):** Werftaufträge erscheinen in der jeweiligen Schiff-Card (`queue_job` via `game/queue_card.py` + `_attach_queue_jobs_to_ship_rows` in `game/shipyard.py`). Seitenkopf nur noch Kompaktstatus (`#shipyard-queue-compact`), kein großes Queue-Panel.

---

## Planet Scope

| Operation | Origin |
|-----------|--------|
| Fleet page | `get_context_planet()` |
| `POST /api/fleet/send` | `origin_planet_id` im Body oder context |
| `GET /api/fleet/state` | `?planet_id=` oder context |
| Ship deduction | Origin planet `planet_ships` |

Flotten-Slots: accountweit über **`navigation_tech`** (Basis 3; Stufe 3→4, 5→5, 8→6, 10→7; danach alle 3 Stufen +1 Slot, ohne Obergrenze). Zählt alle aktiven `fleet_movements`.

Overview zeigt **alle** Bewegungen des Spielers (nicht nur active planet).

---

## World-native targets (GC-590A)

Flotten-Ziele sind **Orte**, nicht primär G:S:P-Koordinaten. Legacy-Koordinaten bleiben interner Adapter; API und Preview liefern zusätzlich `target.world_target`.

| Feld | Bedeutung |
|------|-----------|
| `target_type` | `planet`, `world_colony`, `expedition_world`, `anomaly`, `wreckage`, `enemy_colony` |
| `target_world_key` | Kanonischer Welt-Schlüssel (`field:…`) |
| `target_world_x` / `target_world_y` | Kartenposition |
| `planet_role` | Strategischer Welttyp / Kolonie-Rolle |
| `target_name_key` / `target_name` | Anzeigename (Locale oder Planet) |
| `legacy_coords` | `{galaxy, system, position}` — intern, bis GC-590B UI coords entfernt |

**Owner:** `game/fleet_target.py` — `parse_fleet_target_request()`, `normalize_fleet_target_request()`, `attach_world_target()`.

**API-Eingabe (Priorität):** `target_planet_id` → `world_key` / `target_world_key` → `target_world_x/y` → legacy `target_galaxy/system/position`.

**Endpoints:** `POST /api/fleet/preview`, `POST /api/fleet/send`, `GET|POST /api/fleet/resolve-target` akzeptieren world-native Felder.

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
| **collect** | Eigene Kolonie: lädt Ressourcen bis Cargo-Cap; Ziel verliert Ressourcen; Rückflug; Hub/Origin erhält Fracht bei Rückkehr; Reports siehe [Logistics-Nachrichten](#fleet-logistics-gc-526531) |
| **deploy** | Schiffe + Ressourcen bleiben; movement completed |
| **spy** | Tiered probe intel (resources → fleet → buildings → activity); structured inbox report; Schiffe return |
| **attack** | `simulate_battle()` vs hangar + `planet_defense`; losses, debris, loot (winner), combat reports, return flight — see [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| **hold** | `holding` für 3600s, dann return (ally only wenn Alliance-Schema) |
| **expedition** | Event engine (`expedition_events.py`): weighted outcomes, kanonische Loot-Formel (s. u.), Cargo-Cap = Frachtraum der Expo-Hüllen, optional delay; inbox event-card report (GC-402C) |

### Expedition (GC-402 / 402B / 402C)

| Ticket | Backend / UI | Module |
|--------|----------------|--------|
| **GC-402** | Weighted event roll on arrival; `report_version: 2` metadata | `game/expedition_events.py`, `game/fleet.py` |
| **GC-402B** | Fleet send preview: mission hints, ok/blocked status, expedition auto-position 16 | `static/main.js`, `templates/fleet.html` |
| **GC-402C** | Inbox debrief: event card, risk/find meta, loot chips, theme colors per event type | `static/js/messages.js`, `static/style.css` |

Event keys: `void_scan`, `mineral_deposit`, `fuel_cache`, `debris_salvage`, `nav_interference`, `distress_beacon`, `sensor_glitch`, `ancient_stash`, `pirate_encounter`, `ion_storm`, `ancient_minefield`, `lost_container`, `abandoned_convoy`, `ancient_derelict`, `spatial_rift`, `time_anomaly`, `ancient_beacon`. Roll ist deterministisch pro `movement_id`. **Weight audit (GC-620J):** 124 Punkte gesamt — Loot ~60 %, Combat ~5 %, Hazard ~3 %, Treasure ~6 %, Legendary ~2,4 % (`spatial_rift`, `time_anomaly`, `ancient_beacon` je weight 1); `expedition_event_weight_audit()` für Regression-Tests.

#### Kanonische Expeditions-Loot-Formel (GC-EXPEDITION-LOOT-FINAL)

**Owner:** `game/expedition_events.py` — keine parallele Loot-Engine, kein Economy-Floor, kein globales Hardcap.

Nur Schiffe mit `role: expedition` zählen (Phase 1: **Odyssey** = `solar_skiff`). Kampf- und Frachter-Eskorten erhöhen weder `expo_value` noch Cargo-Cap.

```text
per_hull_value = Summe(build_cost)   # metal + crystal + fuel_cells aus fleet_defs
expo_value     = Σ (expo_hull_count × per_hull_value)
base_loot      = expo_value ** 0.72
final_loot     = min(base_loot × random_factor × profile_mult × event_factor, cargo_capacity)
```

| Faktor | Wert | Quelle |
|--------|------|--------|
| `random_factor` | `uniform(0.66, 1.5)` | Server-RNG pro Event-Roll |
| `profile_mult` | Event-spezifisch (`mult_range` in `_EVENT_LOOT_PROFILES`) | z. B. `ancient_stash` > `mineral_deposit` |
| `event_factor` | Default `1.0` | Vorbereitet für globale Events (`directive_flags.expedition_event_factor`) |
| `cargo_capacity` | `calculate_expedition_loot_cap(ships)` | Summe `cargo` aller Expo-Hüllen (ohne ×50-Multiplikator) |

Referenzwerte (Odyssey, ohne Random/Event): 100 ≈ 18 978 · 200 ≈ 31 260 · 500 ≈ 60 465 · 1 000 ≈ 99 597 · 10 000 ≈ 522 692 Loot-Ressourcen gesamt (vor Split auf metal/crystal/fuel_cells).

Weitere Expo-Schiffe (z. B. `eclipse_runner`) werden automatisch über `role: expedition` + `build_cost` in `expo_value` einbezogen.

**Legendary (GC-620J-A):** `spatial_rift` — 60 % verstärkter Fund (1,4–1,8×, cargo-capped) oder 40 % Rückkehrverzögerung (+25–55 % Flugzeit); `time_anomaly` — 50 % Dilatation (+20–40 % Flugzeit) oder 50 % Kompression (Flavor, kein echter Rückkehrgewinn); optional 30 % Mini-Bonus-Loot; `ancient_beacon` — 1× Premium/Alien/Research-Lootbox + kleine Ressourcen. Piratensieg (GC-620G/H): Verluste + optionale Ressourcenbeute; ~30 % Chance auf kleine Schiffbergung (nur leichte/mittlere Hüllen, Score-Cap). Hazards (GC-620I-A): `ion_storm` verlängert Rückkehr um 20–60 % Flugzeit; `ancient_minefield` verursacht 2–12 % Schiffsverluste ohne Kampf (Hard-Cap ≥1 Schiff). Story/Treasure (GC-620I-B): `lost_container` (~3 %) — Lootbox + kleine Ressourcen; `abandoned_convoy` (~1,6 %) — Ressourcen und/oder Convoy-Salvage; `ancient_derelict` (~0,8 %) — seltenes Mid-Hull + Premium-Cache.

| **colonize** | `colonize_planet()`; verbraucht `seed_ark` |
| **recycle** | Trümmer abbauen (`harvest_debris_at_field`); Fracht auf Rückflug; Report bei Ankunft |

**Berichte (Einzelmissionen):** Transport/Recycle/Deploy/Hold/Spy/Attack/Expedition/Kolonize → Inbox bei **Ziel-Ankunft**; idempotent pro `fleet_id` ohne `report_phase` (GC-521).

**Einzel-`collect`** (Fleet-Send): gleiche Tick-Logik wie Bulk-Collect; ein Ankunftsbericht (`logistics_collect_arrival`); Rückkehrbericht (`logistics_collect_return`) wenn Fracht > 0.

---

## Fleet Logistics (GC-526–533)

Multi-Kolonie-Ressourcenbewegung über **`/logistics`** und `collect_resources` / `distribute_resources` in `game/fleet.py`. Route-Math in `game/fleet_calc.py` (`build_collect_route`, `build_distribute_route`). Spec: [GC-900_LOGISTICS.md](GC-900_LOGISTICS.md).

| Flow | Batch-Typ | Mission pro Leg | Origin (Hub) | Ziele |
|------|-----------|-----------------|--------------|-------|
| **Collect** | `collect_resources` | `collect` | `target_planet_id` (Hub, Rückkehrziel) | `source_planet_ids` — eigene Kolonien ≠ Hub |
| **Distribute** | `distribute_resources` | `transport` | `origin_planet_id` (Hub, Abgang) | `target_planet_ids` — eigene Kolonien ≠ Hub |

- Nur **eigene** Planeten (`validate_logistics_planets` / `validate_collect_source_planet`).
- Deterministische Reihenfolge: Sortierung `galaxy → system → position → planet_id` (`collect_route_sort_key`).
- Jede Leg = **eine** `fleet_movements`-Zeile + **ein** Fleet-Slot (kein Batch-Slot-Rabatt).
- Schiffe werden vom **Hub**-`planet_ships` abgezogen; Fracht bei Distribute beim Send vom Hub debitiert.

### Cargo-Regeln

| Regel | Collect | Distribute |
|-------|---------|------------|
| Schiffstypen | Nur `role == cargo` (`fleet_ships_are_cargo_only`) | gleich |
| Schiffs-Split | `split_ships_across_targets` — Rest je Typ auf **letztes** Ziel | gleich |
| Ressourcen-Modus | `resources_mode`: nur **`all`** (alles Verfügbares am Quell-Planet bis Cargo-Cap) | **`equal`** (Gesamtmenge gleichmäßig) oder **`custom`** (`target_resources` pro Planet) |
| Kapazität | Laden am Ziel bis `calculate_total_cargo(ships)` | `not_enough_cargo`, wenn Leg-Fracht > Leg-Schiff-Cargo |
| Storage-Caps | — (Quelle wird bei Ankunft debited) | **metal/crystal** auf Ziel-Lager begrenzt (`_clamp_distribute_delivery`); **fuel_cells** ohne Storage-Clamp |
| Leere Legs | — | Ziele ohne lieferbare Menge werden übersprungen; `no_deliverable_resources`, wenn nichts übrig |

### Slot-Regeln

- `get_fleet_slot_status(player_id)` → `free` muss **> 0** sein; pro Leg ein Slot. Mehr gewählte Kolonien als freie Slots → Route wird auf **`free`** gekappt (deterministische Sortierung); übersprungene Ziele in Preview (`targets_skipped`). Bei **0** freien Slots: `fleet_slots_full`.
- Basis-Slots: **`navigation_tech`**-Tiers (Fallback 3) — identisch zu Einzel-`send_fleet`; siehe `fleet_slots_for_navigation_level()` in `game/research.py`.
- Bulk-Job blockiert atomisch: zu wenig Schiffe auf dem Hub → Rollback des gesamten Collect/Distribute-POST.

### Nachrichten-Zeitpunkt (GC-530)

Idempotenz: pro `(recipient, category, fleet_id, report_phase)` — kein Doppelreport bei erneutem Tick.

| Flow | Phase | `report_phase` | Wann | Inhalt |
|------|-------|----------------|------|--------|
| Collect | Ziel-Ankunft (Quell-Kolonie) | `logistics_collect_arrival` | `outbound` → `returning` | Abholung abgeschlossen (geladene Menge) |
| Collect | Rückkehr (Hub) | `logistics_collect_return` | `returning` → `completed` | Ressourcen auf Ursprung angekommen (nur wenn Fracht > 0) |
| Distribute | Ziel-Ankunft | `logistics_distribute_arrival` | Ankunft `transport` | Liefermenge an Ziel |
| Distribute | Rückkehr (Hub) | `logistics_distribute_return` | Rückkehr | Nur Schiffs-Rückkehr-Info; **keine** zweite Liefermeldung (`resources` leer in Metadata) |

Metadata (alle Logistics-Reports): `origin_planet_id`, `origin_name`, `target_planet_id`, `target_name`, `target_coords`, `mission_type` (`collect` / `distribute`), `ships`, `resources` / `collected`, `timestamp`, `parent_batch_id` (Bulk), `fleet_id`.

API: `notify_logistics_fleet_report()` in `game/messages.py`. Normale **`transport`**-Einzelmissionen: weiterhin ein Bericht nur bei Ankunft (`notify_transport`, ohne `report_phase`).

### APIs & UI

| Route | Methode | Zweck |
|-------|---------|-------|
| `/logistics` | GET | SSR Collect/Distribute (`templates/logistics.html` → `fleet_logistics.html`) |
| `/api/fleet/logistics/preview` | POST | Server-Plan (Legs, Cargo, Slots, Block-Reason) |
| `/api/fleet/logistics/collect` | POST | `collect_resources` → `{ ok, state }` |
| `/api/fleet/logistics/distribute` | POST | `distribute_resources` → `{ ok, state }` |

Planet-Scope: Hub = aktiver Kontext-Planet (`get_context_planet`) bzw. explizit im Body; Client: `GC.fetchGameAction` + `applyActionState()` (`static/main.js` → `initLogistics()`).

**GC-533 UI/Client:** Kompakte Genesis-Oberfläche (`logistics-page--compact` in `templates/fleet_logistics.html`). Quell-Kolonien, Cargo-Mengen und MAX werden clientseitig validiert; Start erst nach erfolgreichem Preview (`can_launch`). Fehler als Inline-Hinweis + `showNotify`. Cargo-Gate serverseitig: `validate_logistics_manual_ships()` in `game/fleet.py` / `fleet_logistics_validate_ships()` in `game/fleet_api.py`.

**Manuelle QA (GC-533):** [GC-533_MANUAL_QA_LOGISTICS.md](GC-533_MANUAL_QA_LOGISTICS.md), Checkliste [ALPHA_TESTPLAN.md § 12](ALPHA_TESTPLAN.md#12-fleet-logistics-gc-533--manuelle-browser-qa).

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

**Idempotenz:** Statuswechsel nur über `_claim_movement_status()`; wiederholter Tick = No-Op (keine doppelten Nachrichten/Ressourcen/Kolonien/Loot). Siehe GC-524.

**Manuelle Browser-QA:** Missions § 11 (GC-525), Logistics § 12 (GC-533) — [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md).

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
| `/api/fleet/logistics/preview` | POST | Collect/Distribute plan preview |
| `/api/fleet/logistics/collect` | POST | Multi-colony collect batch |
| `/api/fleet/logistics/distribute` | POST | Multi-colony distribute batch |
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
- **Logistics:** `initLogistics()` auf `/logistics` — Tabs Collect/Distribute, debounced Preview, Hub = `data-logistics-origin` / `data-logistics-hub`

Templates: `templates/fleet.html` (Link zu Logistics), `templates/logistics.html` (Wrapper), `templates/fleet_logistics.html` (Markup).

Inbox expedition reports: `static/js/messages.js` → `renderExpeditionReport()` (GC-402C event cards).

---

## Abhängigkeiten

| System | Nutzung |
|--------|---------|
| Galaxy | Koordinaten, target resolution |
| Planet Evolution | `colonize_planet` |
| Alliance | `are_players_allied`, hold mission |
| Research | slots, fuel_efficiency |
| Messages | transport, logistics reports (`report_phase`), spy, combat, expedition |
| Combat | attack resolution — [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Shipyard | `planet_ships` supply |

---

## Placeholder / Phase 2

- Logistics: `auto_cargo` / Preset-only ship selection (`invalid_ships_selection_mode`)
- Recycler UI/PJAX polish (GC-800B) — Backend mission `recycle` ✅ GC-800A
- `fleet_presets.mission_type` CHECK fehlt `colonize` (nur movements migriert in 032)

---

## Tests

```bash
python -m pytest tests/test_fleet.py tests/test_shipyard.py tests/test_galaxy.py tests/test_combat.py -v
```
