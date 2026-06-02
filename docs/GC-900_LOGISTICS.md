# GC-900 — Fleet Logistics (Multi-Colony Resource Movement)

> Epic: Economy / Operations — **Ressourcen zwischen eigenen Kolonien** planbar bewegen  
> Voraussetzung: GC-801/802 State-Sync, GC-800 Recycler ✅, `fleet_movements` + `fleet_batches` vorhanden  
> **Nicht:** neues Fleet-System, parallele Logistics-State-Engine, neue Queue

---

## Problem

Spieler mit mehreren Kolonien können Ressourcen zwar **einzeln** per Fleet-Mission `transport` / `collect` bewegen, aber die **Bulk-Logistics-APIs** sind nur validiert und geben `logistics_not_implemented` zurück:

| Baustein | Status | Ort |
|----------|--------|-----|
| `collect_resources()` | Stub | `game/fleet.py` — `validate_logistics_planets` ✅, Implementierung ❌ |
| `distribute_resources()` | Stub | `game/fleet.py` — gleiches Muster |
| Routes | Stub | `app.py` — `POST /api/fleet/logistics/collect`, `…/distribute` |
| UI | Fehlt | Keine Logistics-Seite; Fleet-UI kennt Missionen nicht |
| Einzel-`collect` | ✅ | `send_fleet` mission `collect` — **ein** Ziel, **eine** Fahrt (nicht GC-900) |

```text
Heute:  Kolonie A → (manuell N× Fleet send) → Hub
GC-900: Hub ← (ein Plan: A+B+C, Cargo-Verteilung, Slot-Check) ← automatisiert
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
- **Cargo-Kapazität** und **Storage-Caps** nur serverseitig (`fleet_calc`, `get_storage_capacity`)
- Ankunft/Rückflug über bestehendes **`process_fleet_tick`** / `fleet_movements` — kein neuer Tick

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
| `auto_cargo` / Preset-only ohne Implementierung | Stub-Modi explizit Phase 2 |

---

## Architektur (GC-000)

| Regel | Umsetzung |
|-------|-----------|
| **Owner** | `game/fleet.py` (Orchestrierung, Movements), `game/fleet_calc.py` (Distanz/Cargo/Fuel), `game/fleet_api.py` (Envelope) |
| **Routes** | `app.py` — dünn; Mutation → `_action_json_response` mit `state` |
| **Bewegungen** | Ausschließlich `fleet_movements`; optional `fleet_batches` zur UI-Gruppierung (wie `mass_expedition`) |
| **Kein Parallel-System** | Kein `logistics_state`, kein zweites Polling |
| **Planet Scope** | Origin = `get_context_planet()` oder explizit `origin_planet_id` / `target_planet_id` im Body; Schiffe von Origin `planet_ships` |
| **Frontend** | Später: `GC.fetchGameAction` → `applyActionState()`; Preview nur Server (`/api/fleet/preview` oder dediziertes Logistics-Preview in 900C) |
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
| `ships_selection_mode` | `manual` (MVP) — `auto_cargo` / `preset` → derzeit Stub |
| `preset_id` | Optional; Preset-Flow Phase 2 |

**Distribute** — `POST /api/fleet/logistics/distribute`

| Feld | Bedeutung |
|------|-----------|
| `origin_planet_id` | **Hub** — Fracht wird hier abgebucht |
| `target_planet_ids` | **Ziel-Kolonien** |
| `resources_mode` | z. B. `equal` — gleichmäßige Verteilung (MVP) |
| `resources` | `{ metal, crystal, fuel_cells }` Gesamtfracht |
| `ships_selection_mode` | `manual` (MVP) |

### Stub-Verhalten heute

```python
# game/fleet.py — gibt immer validated payload + logistics_not_implemented
return False, "logistics_not_implemented", {
    "ok": False,
    "reason": "logistics_not_implemented",
    "message_key": "fleet_logistics_not_implemented",
    "validated": True,
}
```

Routes antworten mit `fleet_ok` / `fleet_err` **ohne** kanonisches `state`-Envelope — **GC-900B** muss auf `_action_json_response(..., finish_source="api_fleet_logistics_*")` umgestellt werden.

### Hilfsfunktionen (bereits vorhanden)

- `validate_logistics_planets(player_id, target_ids, source_ids)` — Ownership-Check
- `mass_expedition()` — Referenz für **Batch + mehrfaches `send_fleet`** mit `batch_id` / Slot-Check
- Mission `collect` (einzeln) — Referenz für **Beladung am Ziel** und **Gutschrift am Origin** bei Return

---

## Empfehlung: Movements + optional Batch

| Option | Beschreibung | Empfehlung |
|--------|--------------|------------|
| A | **1 `fleet_movements` Row pro Quell/Ziel-Paar** (Outbound → Load → Return als Status-Übergänge) | ✅ MVP |
| B | Nur Batch-Eintrag ohne Movements | ❌ widerspricht GC-000 |
| C | Parallele `logistics_jobs` Tabelle | ❌ verboten |

**Batch (optional, empfohlen):**

- `fleet_batches.batch_type` ∈ `collect_resources` | `distribute_resources` (bereits in `fleet_defs.BATCH_TYPES`)
- `fleet_movements.parent_batch_id` verknüpft Einzelfahrten für Overview/UI
- UI zeigt „Logistics Collect #123“ mit N aktiven Flotten

**Mission-Typen (Migration in GC-900B):**

- `collect_resources` — Ankunft: wie `collect`, Beladung bis Cargo-Cap, Return zum Hub
- `distribute_resources` — Abflug: Fracht vom Hub; Ankunft: Gutschrift ans Ziel; Return leer

Alternativ intern `transport`/`collect` nutzen und nur Batch labeln — **weniger klar in Reports**. Empfehlung: **explizite Mission-Strings** + Migration `043`-Stil CHECK-Erweiterung.

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
3. Pro Source: `send_fleet`-ähnlicher Aufruf mit Mission `collect_resources`, Ziel = Source-Koordinaten, Origin = Hub, `resources={}` am Abflug.
4. Ankunft am Source: Beladung bis Cargo-Cap — Priorität MVP: **metal → crystal → fuel_cells** (analog Einzel-`collect`).
5. Return zum Hub: bei Ankunft Ressourcen auf **Hub-Planet** gutschreiben (nicht auf Source).
6. Messages/Reports: Transport-ähnliche Systemnachricht optional (GC-900D).

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

## Distribute Resources (Spezifikation)

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
4. Pro Target: Movement `distribute_resources` mit anteiliger `resources_json` am Abflug.
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

## APIs (Zielvertrag GC-900B/C)

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

`ships` im Body ist **neu zu spezifizieren** in 900B (heute fehlt in Route — nur `preset_id`). Ticket: Route + Handler erweitern.

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

---

## UI (GC-900C / GC-900D)

| Phase | Inhalt |
|-------|--------|
| **900C** | Minimale Logistics-Seite oder Fleet-Tab: Kolonie-Multi-Select (eigene Planeten), Cargo-Schiffe, Preview, Send |
| **900D** | Presets (`fleet_presets`), bessere Overview-Batch-Anzeige, i18n, Reports |

MVP-UI-Regeln:

- PJAX-Navigation; `data-no-pjax` auf Forms
- `GC.fetchGameAction` + `applyActionState`
- Planet-Liste aus Server (eigene Kolonien, nicht Homeworld-only)
- Kein `location.reload`

Ort: neues Template `templates/logistics.html` **oder** Erweiterung `templates/fleet.html` — Entscheidung 900C (eigene Seite bevorzugt bei ≥2 Flows).

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
| **GC-900A** | Diese Spezifikation | `docs/GC-900_LOGISTICS.md`, ROADMAP, PROJECT_INVENTORY |
| **GC-900B** | Collect Backend + Migration Mission + API `state` + Tests | `game/fleet.py`, `app.py`, `migrations/044_*.sql`, `tests/test_fleet_logistics.py` |
| **GC-900C** | Distribute Backend + minimale UI + Tests | `game/fleet.py`, `app.py`, `templates/logistics.html`, `static/main.js` |
| **GC-900D** | UX/Polish: Presets, Overview, Reports, `auto_cargo` | UI + i18n |

Empfohlene Reihenfolge: **900B → 900C → 900D**.

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

### GC-900C — Distribute

| Test | Erwartung |
|------|-----------|
| `test_distribute_debits_origin` | Origin metal↓ beim Start |
| `test_distribute_equal_split` | 3 Targets, gleiche Anteile |
| `test_distribute_respects_storage_cap` | Ziel voll → Überschuss bleibt |
| `test_distribute_empty_return` | Nach Return: Schiffe leer, Origin unverändert (abgesehen von Abzug) |
| `test_distribute_fleet_slots` | Slot-Limit |

Bestehende Tests dürfen nicht brechen: `tests/test_fleet.py` Stub-Tests anpassen auf grün sobald implementiert.

```bash
# Nach 900B
python -m pytest tests/test_fleet_logistics.py tests/test_fleet.py -k "logistics or collect_resources" -v

# Nach 900C
python -m pytest tests/test_fleet_logistics.py -v
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
| **GC-900A** Spec | ✅ |
| **GC-900B** Collect Backend | 📋 |
| **GC-900C** Distribute Backend/UI | 📋 |
| **GC-900D** Logistics UX/Polish | 📋 |
