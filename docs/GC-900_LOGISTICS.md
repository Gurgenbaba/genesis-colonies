# GC-900 — Fleet Logistics (Multi-Colony Resource Movement)

> Epic: Economy / Operations — **Ressourcen zwischen eigenen Kolonien** planbar bewegen  
> Voraussetzung: GC-801/802 State-Sync, GC-800 Recycler ✅, `fleet_movements` + `fleet_batches` vorhanden  
> **Nicht:** neues Fleet-System, parallele Logistics-State-Engine, neue Queue  
> **Status:** Collect + Distribute live (GC-900A–E / GC-526–533). **`auto_cargo` UI-Default** (manuelle Ships nur noch API).

---

## Problem (historisch — gelöst)

Spieler mit mehreren Kolonien brauchten Bulk-Collect/Distribute statt N× Einzel-`transport`/`collect`. MVP + UI sind implementiert; dieses Doc bleibt Spec/Referenz.

```text
Live:  Hub ← (Plan: A+B+C, auto_cargo, Slot-Check) ← automatisiert
UI:    Kolonien markieren → (Mengen bei Distribute) → Start
```

---

## Zielbild (MVP)

Logistics ermöglicht **planbare Ressourcenbewegungen zwischen eigenen Kolonien** unter einem Origin-Planeten (aktiver Kontext / explizit gewählt).

| Flow | Spieler-Intent |
|------|----------------|
| **Collect** | Cargo-Flotten holen Ressourcen von mehreren **eigenen** Kolonien und bringen sie zum **Hub-Planeten** |
| **Distribute** | Hub-Planet sendet gewählte Fracht auf mehrere **eigene** Kolonien; Schiffe kehren **leer** zurück |

MVP-Constraints:

- Nur **Cargo-Schiffe** (`role == cargo` in `fleet_defs`)
- Nur **eigene** Planeten (`validate_logistics_planets` / `_planet_owned_by`)
- **Fleet-Slots:** jede gestartete Ziel-Fahrt verbraucht **1 Slot** (kein Batch-Slot-Rabatt im MVP)
- **Cargo-Kapazität** serverseitig (`fleet_calc`); Storage-Caps auf Zielen werden **ignoriert** (Overflow erlaubt)
- Ankunft/Rückflug über bestehendes **`process_fleet_tick`** / `fleet_movements` — kein neuer Tick
- **`auto_cargo`:** Server wählt freie Frachter am Hub; bei zu wenig Kapazität Teilstart / Mengen-Clamp statt Hard-Fail

---

## Abgrenzung (nicht im MVP)

| Out of scope | Hinweis |
|--------------|---------|
| NPC-Handel / Marketplace | Trader Hub bleibt separat |
| Automatische Dauer-Routen | Phase 2+ |
| Alliance-Logistics | Nur `player_id`-eigene Planeten |
| Combat, Recycler, Expedition | Eigene Missionen (GC-800, GC-402) |
| Neue Ressourcenarten | metal / crystal / fuel_cells |
| Neue Queue-Engine | Queue-Regeln nur für Schiffsbau/Forschung |
| `deploy` bei Distribute | MVP: liefern + leerer Rückflug |
| Preset-only Ships | `ships_selection_mode=preset` weiter Stub |

---

## Architektur (GC-000)

| Regel | Umsetzung |
|-------|-----------|
| **Owner** | `game/fleet.py` (Orchestrierung, Movements), `game/fleet_calc.py` (Distanz/Cargo/Fuel), `game/fleet_api.py` (Envelope) |
| **Routes** | `app.py` — dünn; Mutation → `_action_json_response` mit `state` |
| **Bewegungen** | Ausschließlich `fleet_movements`; optional `fleet_batches` zur UI-Gruppierung (wie `mass_expedition`) |
| **Kein Parallel-System** | Kein `logistics_state`, kein zweites Polling |
| **Planet Scope** | Origin = `get_context_planet()` oder explizit `origin_planet_id` / `target_planet_id` im Body; Schiffe von Origin `planet_ships` |
| **Frontend** | GC-900C: `GC.fetchGameAction` → `applyActionState()`; Preview nur Server |
| **Keine Frontend-Math** | Keine Cargo-/Slot-/Fuel-Berechnung im Client |
| **Idempotenz** | `request_id` / `X-Request-Id` auf POST (wie Build/Fleet send) |

Referenz-Muster: [GC-800_RECYCLER.md](GC-800_RECYCLER.md) (Mission + Tick), [STATE_AJAX.md](STATE_AJAX.md) (Action-State).

---

## Bestehende Code-Verträge (nicht brechen)

### API-Parameter (bereits in `app.py`)

**Collect** — `POST /api/fleet/logistics/collect`

| Feld | Bedeutung |
|------|-----------|
| `target_planet_id` | **Hub** — Planet, an dem Schiffe starten/enden und Ressourcen gutgeschrieben werden |
| `source_planet_ids` | Liste **Quell-Kolonien** (eigene Planeten), von denen abgeholt wird |
| `resources_mode` | z. B. `all` (MVP: alles bis Cargo-Cap) |
| `resources` | Optional explizite Mengen (Phase 2 / `manual` modes) |
| `ships_selection_mode` | **`auto_cargo`** (UI-Default) oder **`manual`** (API/Tests); `preset` → Stub |
| `preset_id` | Optional; Preset-Flow weiter Phase 2 |
| `ships` | Pflicht bei `manual`; bei `auto_cargo` leer / ignoriert — Server allokiert aus Hub-Stock |

**Distribute** — `POST /api/fleet/logistics/distribute`

| Feld | Bedeutung |
|------|-----------|
| `origin_planet_id` | **Hub** — Fracht wird hier abgebucht |
| `target_planet_ids` | **Ziel-Kolonien** |
| `resources_mode` | z. B. `equal` — gleichmäßige Verteilung (MVP) |
| `resources` | `{ metal, crystal, fuel_cells }` Gesamtfracht |
| `ships_selection_mode` | **`auto_cargo`** (UI) oder **`manual`** |

### Live-Verhalten

`collect_resources` / `distribute_resources` orchestrieren `fleet_batches` + N× `send_fleet`. Preview: `POST /api/fleet/logistics/preview` mit gleichem `ships_selection_mode`.

### Hilfsfunktionen (bereits vorhanden)

- `validate_logistics_planets(player_id, target_ids, source_ids)` — Ownership-Check
- `mass_expedition()` — Referenz für **Batch + mehrfaches `send_fleet`** mit `batch_id` / Slot-Check
- Mission `collect` (einzeln) — Referenz für **Beladung am Ziel** und **Gutschrift am Origin** bei Return

---

## Architekturentscheidung: Option A (Orchestrierung)

**GC-900B und Collect-MVP:** Keine neue `mission_type`, **keine Migration**, **kein neuer Tick-Zweig**.

```text
fleet_batches.batch_type = collect_resources
        ↓
N × send_fleet(mission="collect", origin=Hub, target=Source)
        ↓
bestehende Collect-Tick-Logik + Return-Gutschrift am Hub
```

| Was | Rolle |
|-----|--------|
| `batch_type` `collect_resources` | UI/Overview-Gruppierung (wie `mass_expedition`) |
| `mission_type` `collect` | Beladung, Return, `_handle_return` — bereits live |
| `collect_resources` als Mission-String | ❌ nicht für MVP — nur Batch-Label |

**Warum Option A (GC-000):** Fleet-System bleibt eins; Logistics = Planung + Batch + N normale Movements. Referenz: `mass_expedition()` in `game/fleet.py`.

**Distribute (GC-900D):** Gleiches Prinzip bevorzugt — `batch_type` `distribute_resources` + N× `send_fleet(mission="transport", …)` (Details im Distribute-Ticket; eigene Randfälle: Abbuchung, Caps, Split).

| Verboten | Grund |
|----------|--------|
| Parallele `logistics_jobs` | GC-000 Regel 15 |
| Nur Batch ohne Movements | Kein Tick |
| Neuer Mission-Typ nur für Label | Migration + doppelte Tick-Logik ohne Nutzen |

---

## GC-900B — drei Baustellen (Collect Backend)

| # | Baustelle | Heute | Ziel |
|---|-----------|--------|------|
| 1 | **Ships in API** | Route übergibt kein `ships` | Body `ships: { "mule_courier": N }` → Handler; Cargo-only-Validierung |
| 2 | **Envelope** | `fleet_ok` ohne `state` | `_action_json_response` + `applyActionState`-fähiges `state` (GC-801) |
| 3 | **Batch-Orchestrierung** | Stub | Wie `mass_expedition`: `fleet_batches` + Schleife `send_fleet(collect)` + Slot-Check; Schiffe gleichmäßig auf Sources |

**Nicht in 900B:** `distribute_resources`, UI, Migration 044, Presets/`auto_cargo`.

---

## Collect Resources (Spezifikation)

### Spielerbeispiel

```text
Hub (target_planet_id): Hauptplanet
Sources: Kolonie A, B, C
Ships: 30× mule_courier (vom Hub)
```

### Ablauf (Server)

1. Validierung: Ownership, ≥1 Source, Hub ∉ Sources (oder erlaubt skip), nur Cargo-Ships, genug Schiffe am Hub, `free_slots >= Anzahl geplanter Movements`.
2. **Schiffverteilung (MVP):** Gleichmäßig auf Sources aufteilen (ganzzahlig pro Source); Rest auf letzte Source oder Ablehnung wenn nicht teilbar — **im Ticket festnageln**.
3. Pro Source: `send_fleet(mission="collect", origin_planet_id=Hub, target_planet_id=Source, ships=Anteil, resources={}, batch_id=…)`.
4. Ankunft am Source: bestehende `collect`-Tick-Logik — Beladung metal → crystal → fuel_cells bis Cargo-Cap.
5. Return zum Hub: bestehendes `_handle_return` — Gutschrift auf **Hub** (`origin_planet_id`).
6. Collect-Reports: bestehende `fleet_collect_report_*` (optional UX in GC-900E).

### Fehlerfälle

| Reason | Bedingung |
|--------|-----------|
| `planet_not_owned` | Fremder Planet in Liste |
| `no_planets` | Leere Liste |
| `not_enough_ships` | Hub hat nicht genug Cargo-Schiffe |
| `fleet_slots_full` | `free_slots < needed_movements` |
| `no_cargo_ships` | Auswahl enthält Non-Cargo |
| `origin_not_found` | Ungültige Planet-IDs |

---

## Distribute Resources (Spezifikation — GC-900D/E)

> **Nicht GC-900B.** Größerer Brocken: Cargo-Split, Storage-Caps, Ressourcenreservierung, Zielverteilung.

### Spielerbeispiel

```text
Origin: Hauptplanet
Targets: Kolonie A, B, C
Cargo: 300k metal, 150k crystal, 500 fuel_cells
Ships: 10× mule_courier
```

### Ablauf (Server)

1. Validierung: Ownership, Ressourcen am Origin verfügbar, Cargo-Cap ≥ geplante Fracht, Slots, Cargo-Ships.
2. **Fracht reservieren/abbuchen** am Origin beim Start (atomar mit Movement-Erstellung).
3. **Verteilung (MVP `resources_mode=equal`):** Gesamtfracht gleichmäßig auf Targets; pro Target max. Ziel-Storage-Cap — Überschuss **bleibt am Origin** (nicht senden).
4. Pro Target: Orchestrierung (Ziel: `transport` + `batch_type` `distribute_resources`; kein neuer Mission-Typ ohne zwingenden Grund).
5. Ankunft: Gutschrift ans Ziel; Movement → `returning` leer.
6. Return am Origin: keine Fracht an Bord.

### MVP-Designentscheidung

- **Kein Deploy** — Spieler erwartet „Lieferung“, nicht Stationierung.
- Schiffe kehren leer zurück (gleiches Muster wie `transport` nach Drop-off).

---

## Fleet Slots (MVP)

| Regel | Wert |
|-------|------|
| Slot-Kosten | **1 Slot pro gestarteter Movement** |
| Prüfung | `get_fleet_slot_status()` vor Planung; Abbruch wenn `count + planned > max` |
| Teilstart | **Nicht** im MVP — entweder vollständiger Plan oder `fleet_slots_full` |
| Batch zählt als 1 Slot | ❌ später (Logistics-Tech / Phase 2) |

---

## Cargo-Schiffe (MVP)

Erlaubte Keys (role `cargo`):

- `mule_courier`
- `atlas_hauler`
- `nebula_frigate`

Validierung: `get_ship(key)["role"] == "cargo"`; unbekannte Keys → `unknown_ship`.

---

## APIs (Zielvertrag)

### Collect — GC-900B

### Endpunkte (existieren, Verhalten ändern)

```http
POST /api/fleet/logistics/collect
POST /api/fleet/logistics/distribute
```

### Request (Collect — Beispiel)

```json
{
  "target_planet_id": 12,
  "source_planet_ids": [34, 35, 36],
  "ships": { "mule_courier": 30 },
  "resources_mode": "all",
  "ships_selection_mode": "manual",
  "request_id": "uuid"
}
```

`ships` im Body: **GC-900B** Route + `collect_resources()` erweitern (Reality-Check: fehlte in `app.py`).

### Response (kanonisch nach Implementierung)

```json
{
  "ok": true,
  "reason": "",
  "state": { "ok": true, "active_planet_id": 12, "resources": {}, "build_queue": {}, "...": "..." },
  "data": {
    "batch": { "id": 1, "batch_type": "collect_resources", "total_fleets": 3 },
    "started": [{ "source_planet_id": 34, "fleet_id": 101 }],
    "skipped": [],
    "active_slots": { "active": 3, "max": 5, "free": 0 }
  }
}
```

Fehler: `ok: false`, trotzdem **`state`** nach Mutation wo sinnvoll (GC-801).

### Distribute — GC-900D ✅

`POST /api/fleet/logistics/distribute` — `distribute_resources()` + `_action_json_response` (Option A: `transport` + `batch_type=distribute_resources`).

---

## UI

| Ticket | Inhalt |
|--------|--------|
| **GC-900C** | Collect UI: Multi-Select eigene Kolonien, Hub, Cargo-Schiffe, Send → `/api/fleet/logistics/collect` |
| **GC-900E** | Distribute UI + Polish: Presets, Batch-Overview — **`auto_cargo` live** (UI-Default); Preset-only weiter offen |

MVP-UI-Regeln:

- PJAX-Navigation; `data-no-pjax` auf Forms
- `GC.fetchGameAction` + `applyActionState`
- Planet-Liste aus Server (eigene Kolonien, nicht Homeworld-only)
- Kein `location.reload`

Ort: `templates/logistics.html` oder Fleet-Tab — Entscheidung **GC-900C** (Collect zuerst).

---

## Unterschied: Logistics vs. Einzelmissionen

| Aspekt | `collect` / `transport` (send) | GC-900 Logistics |
|--------|-------------------------------|------------------|
| Ziele | 1 Koordinate | N eigene Planeten |
| Planung | Spieler pro Trip | Ein POST, Server plant N Movements |
| API | `/api/fleet/send` | `/api/fleet/logistics/*` |
| Batch | optional | empfohlen |

Recycler `recycle` bleibt **Debris am Feldkoordinaten** — kein Logistics.

---

## Ticket-Split

| Ticket | Scope | Dateien (max. 5) |
|--------|--------|------------------|
| **GC-900A** | Spezifikation + Option A | Docs ✅ |
| **GC-900B** | **Collect Backend only** — Option A, `ships`, `_action_json_response`, Batch+`send_fleet(collect)` | `game/fleet.py`, `app.py`, `tests/test_fleet_logistics.py` |
| **GC-900C** | **Collect UI** | `templates/logistics.html` oder `fleet.html`, `static/main.js`, `app.py` (route) |
| **GC-900D** | **Distribute Backend** — Split, Caps, `transport` orchestration | ✅ `game/fleet.py`, `app.py`, Tests |
| **GC-900E** | **Distribute UI** + Polish (Presets, Overview, Reports) | UI + i18n |

Reihenfolge: **900B → 900C → 900D → 900E → GC-700**.

---

## Tests (Planung)

### GC-900B — Collect

| Test | Erwartung |
|------|-----------|
| `test_collect_logistics_only_own_planets` | Fremder Planet → `planet_not_owned` |
| `test_collect_logistics_requires_cargo_ships` | Fighter-only → Fehler |
| `test_collect_logistics_respects_fleet_slots` | `free_slots` zu klein → `fleet_slots_full` |
| `test_collect_logistics_ship_split` | 30 Ships, 3 Sources → 10/10/10 |
| `test_collect_logistics_pickup_and_return` | Nach Tick: Hub metal↑, Source metal↓ |
| `test_collect_logistics_active_planet_scope` | Hub = `target_planet_id`, Schiffe vom Hub |
| `test_collect_logistics_api_returns_state` | POST → `state.resources` frisch |

### GC-900D — Distribute (Backend)

| Test | Erwartung |
|------|-----------|
| `test_distribute_debits_origin` | Origin metal↓ beim Start |
| `test_distribute_equal_split` | 3 Targets, gleiche Anteile |
| `test_distribute_respects_storage_cap` | Ziel voll → Überschuss bleibt |
| `test_distribute_empty_return` | Nach Return: Schiffe leer |
| `test_distribute_fleet_slots` | Slot-Limit |

Bestehende Tests: `test_logistics_scaffold_response` in `test_fleet.py` nach 900B auf Erfolgspfad anpassen.

```bash
# Nach 900B
python -m pytest tests/test_fleet_logistics.py tests/test_fleet.py -k "logistics or collect" -v

# Nach 900D
python -m pytest tests/test_fleet_logistics.py -k distribute -v
```

---

## Manual QA (nach Implementierung)

1. Zwei Kolonien + Hub; unterschiedliche Ressourcenstände.
2. **Collect:** Hub wählen, A+B als Sources, Cargo senden → Hub-Ressourcen steigen ohne F5.
3. **Distribute:** Fracht vom Hub, Targets A+B → Ziele erhalten Fracht, Hub korrekt reduziert.
4. Fleet-Slots: Plan mit zu vielen Zielen → klare Fehlermeldung.
5. Planetwechsel (GC-802): Origin wechseln → Logistics-Seite zeigt neuen Hub.
6. Galaxy-Shortcut irrelevant; Fleet-Origin = aktiver Planet.

---

## Referenzen

- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Movements, Slots, Missionen
- [PLANET_SCOPE.md](PLANET_SCOPE.md) — `get_context_planet()`
- [STATE_AJAX.md](STATE_AJAX.md) — Action-State
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) — nur indirekt (kein Logistics-Queue)
- [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) — Modul-Matrix
- [ROADMAP.md](ROADMAP.md) — Epic-Reihenfolge

---

## Ticket-Status

| Ticket | Status |
|--------|--------|
| **GC-900A** Spec (+ Option A) | ✅ |
| **GC-900B** Collect Backend | 📋 |
| **GC-900C** Collect UI | 📋 |
| **GC-900D** Distribute Backend | ✅ |
| **GC-900E** Distribute UI / Polish | 📋 |
