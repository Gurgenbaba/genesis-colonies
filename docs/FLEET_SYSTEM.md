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
- `build_cost`: metal, crystal, fuel_cells (fuel_cells auf Mid/High-Tier; Odyssey unverändert)
- Legacy-Key-Aliases für alte Saves
- `role` (primär) + optionale `roles`-Liste; Owner: `ship_roles()` / `ship_has_role()` / `ship_display_role()` in `fleet_defs.py`
- Werft-/Techtree-Reihenfolge: `sort_ship_keys_by_role()` (`SHIP_ROLE_DISPLAY_ORDER`: cargo → expedition → combat → scout → spy → recycle → colony)
- `eclipse_runner` (Voidrunner): Hybrid `roles: [expedition, combat]` (GC-SHIP-1) — bau- und expo-fähig ab Werft L7; zählt für Loot (expedition) **und** Piratenkampf (combat), Verlust-Priorität wie Kampf

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

**Formel (ein Produktionszyklus):**

```text
unit_seconds = ceil(
  build_seconds × 0.975^(yard_level − 1)
  ÷ shipyard_speed
  ÷ shipyard_time_speed
)
```

Konstante: `BUILD_TIME_LEVEL_FACTOR = 0.975` (−2.5 % Schiffbauzeit pro Werft-Stufe über 1, GC-863A).  
Ergebnis: `max(1, …)` Sekunden — Funktionen `unit_build_seconds()` / `_effective_build_seconds()`.

**Progressive Lieferung (Mehrfachauftrag):**

| Konzept | Formel / Owner |
|---------|----------------|
| Yard-Kapazität pro Zyklus | `max(1, floor(1 + level×5 + level^2.3))` — z. B. L1=7, L2=15, L5=66, L10=250, L50≈8335 |
| Einheiten pro Zyklus | = Yard-Kapazität (alle Schiffstypen gleich; kein Gewicht) |
| Auftragsdauer | `ceil(amount / capacity) × unit_seconds` (`production_job_duration_seconds`) |
| Live-Restzeit | `production_live_order_remaining_seconds` → `finish_at` (Sync bei Werft-Upgrade) |

Beispiel Speed ×1, Werft L1 (Kapazität 7), `mule_courier` (`build_seconds = 120`):  
`unit_seconds = 120` → Auftrag über 10 Schiffe = `ceil(10/7) × 120 = 240 s`.

Kosten: `fleet_defs.build_cost` — **kein** Level-Multiplier (metal/crystal/fuel_cells direkt aus Def).

Cancel-Refund: `shipyard_queue` → `queue_refund.refund_from_stored_costs` (GC-831).

Analoges Batch-Muster für Verteidigung: [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) (Unlock über `defense_factory`; Zykluszeit/Kapazität über Orbitalwerft + `defense_time_speed`).

**Queue-UX (GC-UNIT-QUEUE-DEDUP-001):** Werft ist eine **Unit-Queue** — Aufträge erscheinen ausschließlich in der zentralen Mini-Bauschleife (`#shipyard-mini-queue` / `render_page_mini_queue_strip`: Status, Menge, Timer, Fortschritt, Timekeeper ⚡, Abbrechen). Schiff-Cards enthalten keine Queue-UI. Serializer (`map_shipyard_queue_to_card_jobs`, `mini_queue_jobs`) bleiben für Strip/HUD; `queue_job` am Ship-Row ist optional und wird nicht in der Card gerendert.

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

## World-native targets (GC-590A — Dev/Legacy)

Spieler-Hauptpfad nutzt **`target_galaxy` / `target_system` / `target_position`** (klassische Slots). `world_key` bleibt optional für Dev-Preview / Legacy (Strategic Worlds, Salvage).

| Feld | Bedeutung |
|------|-----------|
| `target_type` | `planet`, `world_colony`, `expedition_world`, `anomaly`, `wreckage`, `enemy_colony`, `empty_slot` |
| `target_world_key` | Optional — Welt-Schlüssel (`field:…`) für Map/Legacy |
| `target_world_x` / `target_world_y` | Kartenposition (Dev) |
| `planet_role` | Strategischer Welttyp / Kolonie-Rolle |
| `target_name_key` / `target_name` | Anzeigename (Locale oder Planet) |
| `legacy_coords` | `{galaxy, system, position}` — **kanonisch für Spieler** |

**Owner:** `game/fleet_target.py` — `parse_fleet_target_request()`, `normalize_fleet_target_request()`, `attach_world_target()`.

**API-Eingabe (Priorität):** `target_planet_id` → `target_galaxy/system/position` (Spieler) → optional `world_key` / `target_world_key` (Dev/Legacy).

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

Event keys: `void_scan`, `mineral_deposit`, `fuel_cache`, `debris_salvage`, `nav_interference`, `distress_beacon`, `sensor_glitch`, `ancient_stash`, `pirate_encounter`, `ion_storm`, `ancient_minefield`, `lost_container`, `abandoned_convoy`, `ancient_derelict`, `spatial_rift`, `time_anomaly`, `ancient_beacon`, `lost_colony`, `rogue_ai`. Roll ist deterministisch pro `movement_id`. **Weight audit (GC-EXPO-W1 / GC-620J):** 120 Punkte gesamt — Loot **60 %**, Combat ~4 %, Hazard ~3 %, Neutral ~10 %, Delay ~10 %, Treasure ~8 %, Legendary ~4 % (`spatial_rift`, `time_anomaly`, `ancient_beacon`, `lost_colony`, `rogue_ai` je weight 1); `expedition_event_weight_audit()` für Regression-Tests.

#### Kanonische Expeditions-Loot-Formel (GC-EXPEDITION-LOOT-FINAL)

**Owner:** `game/expedition_events.py` — keine parallele Loot-Engine, kein Economy-Floor, kein globales Hardcap.

Nur Schiffe mit `role: expedition` zählen (Phase 1: **Odyssey** = `solar_skiff`). Kampf-Eskorten erhöhen weder `expo_value` noch Cargo-Cap; Frachter (`role: cargo`) erhöhen nur die Bergungskapazität.

**Drei Säulen:**

| Aspekt | Zählt | Nicht |
|--------|-------|-------|
| **Loot** (`expo_value`) | Expo-Schiffe | Eskorten, Frachter |
| **Bergung** (`cargo_capacity`) | Expo-Frachtraum + Frachter | Kampf-Eskorten |
| **Piratenkampf** (`fleet_value`) | Combat-Eskorten (`role: combat`, inkl. Hybrid) | Expo-Hüllen skalieren **Risiko** (Piratenstärke), kämpfen nicht selbst; Frachter zählen nicht |

**Verluste (Expo-Balance, GC-EXPO-P1/P2):** Kampf-Eskorten (`role: combat`) absorbieren Schiffsverluste **zuerst**. **Piraten:** Recycler (`role: recycle`) sind kampffrei und bergen das ephemere TF; Verluste gehen Eskorten → Expo-Hüllen. **Minenfeld:** unverändert combat → recycle → expedition. Piraten-Event-Gewicht 5/120 (~4 %); Verlustbänder: Sieg 1–6 %, knapp 3–10 %, Niederlage 5–14 %. Piratenstärke `expo_risk × 0.40–0.75`; ohne Eskorte Desperation-Kampf bei 18 % von `expo_risk`.

**Escort-Skalierung (GC-SHIP):** `escort_ratio = escort_combat_value / expedition_hull_value` — ein einzelnes Kampfschiff bei großer Odyssey-Flotte bringt kaum Schutz. Piratenstärke skaliert mit `expedition_hull_value`; Kampfkraft nur aus Eskorten. Owner: `build_expedition_fleet_rating()` / `resolve_pirate_encounter()` in `expedition_events.py`. Preview + Report liefern `expedition_rating` (escort_ratio, voidrunner_bonus).

**Voidrunner-Bonus:** +25 % Gewicht/Loot-Qualität bei positiven Fund-Events (einmal pro Flotte, serverseitig) — kein Piraten-Schutz-Bonus.

**Piraten-Trümmerfeld (Expo, GC-EXPO-P2/P3):** Nach Piratenkontakt mit Verlusten entsteht ein **ephemeres TF** (Spieler- + bei Sieg ~80 % Piraten-Wrack-Punkte als virtuelle Hüllen, kanonische `calculate_combat_debris`). Mitgeschickte Recycler überleben den Piratenkampf und bergen sofort in Recycler-Frachtraum (nicht Expo-Cargo-Cap); Rest verfällt. Kein persistentes Galaxy-Debris-Feld.

**Fleet preview / reports (GC-EXPO-UX):** Mission feedback zeigt Server-`expedition_rating` (Escort-Cover, Voidrunner) plus Recycler-Hinweis; Mass-Expo Preview trennt `usable_slots` / `reserved_slots` / offene Flotten-Slots. Inbox-Report zeigt `daily_efficiency_pct`, Cargo-Cap vs. Rohfund und Piraten-TF-Bergung durch Recycler (display-only).

```text
per_hull_value = Summe(build_cost)   # metal + crystal + fuel_cells aus fleet_defs
per_hull_expo  = per_hull_value ** 0.72
expo_value     = Σ (expo_hull_count × per_hull_expo)
base_loot      = expo_value
final_loot     = min(base_loot × random_factor × profile_mult × event_factor, cargo_capacity)
```

| Faktor | Wert | Quelle |
|--------|------|--------|
| `random_factor` | `uniform(0.66, 1.5)` | Server-RNG pro Event-Roll |
| `profile_mult` | Event-spezifisch (`mult_range` in `_EVENT_LOOT_PROFILES`) | z. B. `ancient_stash` > `mineral_deposit` |
| `event_factor` | Default `1.0` | Vorbereitet für globale Events (`directive_flags.expedition_event_factor`) |
| `cargo_capacity` | `calculate_expedition_loot_cap(ships)` | Summe `cargo` von Expo-Hüllen + Frachtern (`role: cargo`) |

Referenzwerte (Odyssey, ohne Random/Event; Exponent pro Hülle, linear in Anzahl): 1 ≈ 689 · 10 ≈ 6 890 · 100 ≈ 68 904 · 1 000 ≈ 689 042 · 10 000 ≈ 6 890 422 Loot-Ressourcen gesamt (vor Split auf metal/crystal/fuel_cells).

Weitere Expo-Schiffe (z. B. `eclipse_runner`) werden automatisch über `role: expedition` + `build_cost` in `expo_value` einbezogen.

**Tages-Diminishing Returns (GC-EXPEDITION-DAILY):** Pro Spieler und UTC-Tag zählt der Server abgeschlossene Expeditionen (`expedition_daily_value.expedition_count`). Die **nächste** Expedition multipliziert Ressourcen-Loot mit `daily_efficiency_mult` (100 % für die ersten 30 Expeditionen/Tag, dann −5 % pro weiteren 30, Floor 45 %). Reset um UTC-Mitternacht (`day_bucket = floor(unix/86400)`). Flottengröße/`expo_value` beeinflusst die Effizienz nicht. Voidrunner-Event-Chancen bleiben; bei gedrosselter Effizienz liefern zusätzliche Events automatisch weniger Ressourcen. Owner: `expedition_daily_efficiency_multiplier()`, `record_expedition_daily_value()` in `expedition_events.py`.

**Legendary (GC-620J-A/B):** `spatial_rift` — 60 % verstärkter Fund (1,4–1,8×, cargo-capped) oder 40 % Rückkehrverzögerung (+25–55 % Flugzeit); `time_anomaly` — 50 % Dilatation (+20–40 % Flugzeit) oder 50 % **echte Kompression** (Rückflugdauer −15–35 %); optional 30 % Mini-Bonus-Loot; `ancient_beacon` — 1× Premium/Alien/Research-Lootbox + kleine Ressourcen; `lost_colony` — Versorgungscache oder Echo-Delay; `rogue_ai` — Research-Capture oder Hostile-Delay. **Directive flags (GC-EXPO-DIR):** `expedition_legendary_bonus` hebt Legendary-Gewichte; `expedition_slot_bonus` erhöht Flotten-Slots. **Familiarity (GC-583D-D2):** mapped/stabilized/outpost_prepared → leichter Loot-Mult und weniger Risk-Gewicht auf World-Expos. Piratensieg (GC-620G/H + GC-EXPO-P1/P3): Verluste zuerst an Eskorten (Recycler kampffrei); ~45 % Chance auf Schiffbergung (55 % none / 35 % small / 10 % rare; nur leichte/mittlere Hüllen, Score-Cap). Hazards (GC-620I-A): `ion_storm` verlängert Rückkehr um 20–60 % Flugzeit; `ancient_minefield` verursacht 2–8 % Schiffsverluste ohne Kampf (Hard-Cap ≥1 Schiff, Eskorten zuerst, dann Recycler). Story/Treasure (GC-620I-B): `lost_container` — Lootbox + kleine Ressourcen; `abandoned_convoy` — Ressourcen und/oder Convoy-Salvage; `ancient_derelict` — seltenes Mid-Hull + Premium-Cache. Zusätzliche Lootbox-Chancen auf normalen Loot-Events sind niedrig (1–8 % pro Event-Roll).

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
| Schiffs-Auswahl | UI: **`auto_cargo`** (Default); API: `manual` bleibt gültig | gleich |
| Auto-Allokation | `allocate_auto_cargo_ships` — Bedarf = Summe Quellen-Ressourcen; bei Mangel **alle** freien Frachter, Teilstart | `allocate_auto_cargo_ships_for_targets` — genug Cargo pro Leg für Equal-Split; bei Mangel clamp |
| Schiffs-Split | `auto_cargo`: `split_ships_by_weights` (Ressourcen pro Quelle); `manual`: `split_ships_across_targets` | `split_ships_across_targets` |
| Ressourcen-Modus | `resources_mode`: nur **`all`** (alles Verfügbares am Quell-Planet bis Cargo-Cap) | **`equal`** (Gesamtmenge gleichmäßig) oder **`custom`** (`target_resources` pro Planet) |
| Kapazität | Laden am Ziel bis `calculate_total_cargo(ships)` | `manual`: `not_enough_cargo` wenn Leg-Fracht > Leg-Cargo; `auto_cargo`: Mengen auf Leg-Cargo kappen (`load_resources_up_to_cargo`) |
| Storage-Caps | — (Logistik ignoriert Ziel-Lager; Overflow erlaubt) | — (Logistik ignoriert Ziel-Lager; Overflow erlaubt) |
| Leere Legs | `auto_cargo`: 0-Schiff-Legs → `skipped` | Ziele ohne lieferbare Menge werden übersprungen; `no_deliverable_resources`, wenn nichts übrig |

### Slot-Regeln

- `get_fleet_slot_status(player_id)` → `free` muss **> 0** sein; pro Leg ein Slot. Logistik nutzt **alle** freien Slots (kein `MASS_EXPEDITION_SLOT_RESERVE` — Reserve nur bei Mass-Expedition). Mehr gewählte Kolonien als freie Slots → Route auf **`free`** gekappt (deterministische Sortierung; Equal-Split erst danach); übersprungene Ziele in Preview (`targets_skipped`). Bei **0** freien Slots: `fleet_slots_full`.
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

**GC-533 UI/Client:** Kompakte Genesis-Oberfläche (`logistics-page--compact`). Kolonien markieren (inkl. Alle/Keine), Distribute: Gesamtmengen eingeben — **keine manuelle Frachter-Auswahl**. Client sendet `ships_selection_mode: "auto_cargo"`. Start erst nach erfolgreichem Preview (`can_launch`). Fehler als Inline-Hinweis + `showNotify`. Manual-API weiter über `validate_logistics_manual_ships()`.

**Manuelle QA (GC-533):** [GC-533_MANUAL_QA_LOGISTICS.md](GC-533_MANUAL_QA_LOGISTICS.md), Checkliste [ALPHA_TESTPLAN.md § 12](ALPHA_TESTPLAN.md#12-fleet-logistics-gc-533--manuelle-browser-qa).

---

## Tick

`process_fleet_tick(player_id=None)` (global) / `process_fleet_tick(player_id=…)` (scoped refresh):

- Ankünfte verarbeiten
- Hold-Ende → return
- Returns abschließen

**Globaler Worker:** `game/fleet_worker.run_fleet_worker()` — verarbeitet fällige Bewegungen **aller** Spieler, auch wenn niemand online ist. HTTP cron: `POST /api/internal/cron/fleet-tick` (Bearer `GC_INTERNAL_CRON_TOKEN`); piggyback auf Ranking-Cron; throttled safety net bei Live-Requests (`_load_page_live_context`). Intervall: `GC_FLEET_WORKER_INTERVAL_SEC` (default 60); bei global fälligen Flotten wird sofort getickt.

Aufgerufen von:

- `game/fleet_worker.run_fleet_worker()` (global, cron + request safety net)
- `GET /api/game-state` / Page-Load (Spieler-scope + global safety net)
- `queue_engine.finish_due_work()` (fleet_arrivals / fleet_returns counts)
- `scripts/run_tick.py` / Admin queue tick (global fleet pass)

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
| `/api/fleet/mass-expedition` | POST | Wave expeditions (GC-981 split; **reserves 3 fleet slots** — uses `free − 3` only) |
| `/api/fleet/mass-expedition/preview` | POST | Split preview (`usable_slots`, `reserved_slots`) |
| `/api/fleet/logistics/preview` | POST | Collect/Distribute plan preview |
| `/api/fleet/logistics/collect` | POST | Multi-colony collect batch |
| `/api/fleet/logistics/distribute` | POST | Multi-colony distribute batch |
| `/api/fleet/dev/seed-ships` | POST | Debug seed |

Response envelope: `{ ok, error, message_key, data }` via `fleet_api.py`.

---

## Frontend (`static/main.js`)

- Module: `GC.modules.fleet` → `initFleet()`
- Forms: `data-no-pjax` (fetch-only send)
- `scheduleFleetStateRefresh()` / `refreshFleetState()` — coalesced (ein In-Flight-Request); nach Actions und Countdown-Zero
- `applyLiveState` → `renderActiveFleets` patched die aktive Liste (Signatur); kein erneutes `initFleet()` nur wegen State
- Countdown-Zero: kein Reload pro Zeile — debounce + ein Game-State-Refresh (`fleet_countdown_expired`)
- Mobile Fleet-Drawer: `is-show-all` / „Weniger anzeigen“ bleibt; Sheet-Layout nur bei Expand-Änderung
- Realigns `planet_id` from `GC.lastState.active_planet_id`
- Galaxy prefill: `applyFleetUrlPrefill()` from query params
- **GC-402B:** Mission feedback panel (`data-fleet-mission-feedback`), preview status `is-ok` / `is-blocked`, expedition → position 16
- **Logistics:** `initLogistics()` auf `/logistics` — Tabs Collect/Distribute, debounced Preview, Hub = `data-logistics-origin` / `data-logistics-hub`
- **GC-FLEET-NOTIFICATION-BATCH-001:** Expeditions-/Missionsberichte bleiben einzeln im Posteingang; UI-Toasts werden gruppiert

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

- Logistics: Preset-only ship selection (`preset` → `invalid_ships_selection_mode`)
- Recycler UI/PJAX polish (GC-800B) — Backend mission `recycle` ✅ GC-800A
- `fleet_presets.mission_type` CHECK fehlt `colonize` (nur movements migriert in 032)

---

## Tests

```bash
python -m pytest tests/test_fleet.py tests/test_shipyard.py tests/test_galaxy.py tests/test_combat.py -v
```

---

## Player Article

```yaml
---
codex_id: fleet
band: II
difficulty: beginner
estimated_read: 5 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
routes:
  - fleet_view
  - shipyard_view
related_codex:
  - galaxy
  - expansion
  - combat
  - resources
terminology: GENESIS_TERMINOLOGY
unlock:
  type: building
  building: orbital_shipyard
teaser_key: codex_unlock_fleet_teaser
---
```

## Quick Help

Flotten verbinden deine Welten: Transport, Kolonisierung mit Seed Ark, Expeditionen, Angriff und Logistik — Schiffe vom **Abgang-Planeten**, Slots über Navigation-Tech.

## Summary

Das Fleet-System verwaltet **Schiffe pro Welt**, **Flottenbewegungen** imperiumsweit und Missionen bei Ankunft. Schiffsbau läuft über die **Orbitalwerft** und Werft-Queue. Flottenslots sind account-weit durch **Navigation-Tech** erweiterbar.

## Why

Ohne Flotten keine Expansion (Seed Ark), keine Ressourcen-Logistik zwischen Kolonien, keine Expeditionen und kein PvP. Flotten sind die **operative Hand** des Imperiums — Spieler wählen Ziele über **klassische Koordinaten** `[G:S:P]`; `world_key` bleibt optional (Dev/Legacy).

## How it works

- Baue Schiffe in der **Orbitalwerft** auf der gewünschten Abgang-Welt.
- **Fleet-Seite:** Schiffe auswählen, Mission, Ziel (Kolonie, Welt auf der Karte oder Koordinaten).
- **Missionen (Auszug):** Transport, Logistik, Stationieren, Spionage, Angriff, Halten, Expedition, Kolonisierung, Recycler.
- **Kolonisierung:** Kolonisierungs-Mission mit Seed Ark in der Flotte → Outpost-Phase (Expansion Protocol).
- **Expedition:** Event-Engine bei Ankunft — Berichte in Nachrichten; Expo-Schiffe tragen Loot-Rolle.
- **Logistics** (`/logistics`): Sammeln/Verteilen zwischen eigenen Welten über Hub.
- Flugzeit und Brennzellen: Server-Preview — UI zeigt nur Serverdaten.
- Technische Schiffswerte: Schiff-Detail / Technische Daten — nicht Codex.

## Related Systems

- galaxy
- expansion
- combat
- defense
- resources
- buildings

## Commander Tips

- Flotten-Abgang immer mit aktivem Planet abstimmen — Schiffe liegen planetengebunden.
- Navigation-Tech für mehr parallele Flotten priorisieren.
- Expedition: Expo-Hüllen für Funde; Frachter für Bergungskapazität — Rollen beachten.

## FAQ

**Warum kann ich keine Flotte senden?**
Keine Schiffe, kein Slot frei, ungültiges Ziel oder fehlende Mission-Voraussetzung (z. B. Seed Ark für Kolonisierung).

**Wo sind alle meine Flotten?**
Overview und Fleet zeigen **alle** Bewegungen — nicht nur die der aktiven Welt.

## Discord Summary

**Flotte — Missionen und Imperium-Operationen**

Schiffe pro Welt, Bewegungen imperiumsweit. Orbitalwerft nötig. Missionen: Transport, Kolonisierung, Expedition, Angriff, Logistik. Ziele: Welten und Koordinaten. Navigation-Tech = mehr Slots.
