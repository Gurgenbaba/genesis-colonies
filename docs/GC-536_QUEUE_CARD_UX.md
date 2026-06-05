# GC-536 — Queue Card UX (Epic)

> **Keine große Queue-Liste mehr als Haupt-UX.**  
> Jede Queue lebt dort, wo der Auftrag gestartet wurde.

Stand: v1.5.3 · Epic (nicht direkt implementieren)

Verwandt: [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) (Server-Logik), [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) (Regression), [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)

---

## UX-Regel (global)

| Verboten | Pflicht |
|----------|---------|
| Volle Queue-Liste als primäre Seiten-UX (`gc-prog-queue-panel` oben) | Queue-Status **in der Card** des betroffenen Items |
| Client-seitige Queue-Neuordnung / Timer-Rechnung | Anzeige aus Server-`state` (`start_at`, `finish_at`, `progress`) |
| Parallele Queue-Datenformate pro Domäne | Ein **Queue Card Contract** (GC-536A) für alle Domänen |

**Shell / Overview:** Nur **Kompakt-Zähler** — kein Ersatz für Card-Queues.

```text
🏗 3 Bauaufträge
🔬 1 Forschung
🚀 5 Werftaufträge
```

Overview **Aktivitäten** bleibt: ein aktiver Job pro Kategorie + Link zur Seite (bestehend). Keine vollständige Job-Liste auf Overview.

---

## System → Card Mapping

| System | Queue in Card | Scope | Owner-Modul |
|--------|---------------|-------|-------------|
| Gebäude | Gebäude-Card | Planet | `game/buildings.py` |
| Account-Forschung | Forschungs-Card | Spieler | `game/research.py` |
| Werft | Schiff-Card | Planet | `game/shipyard_queue.py` |
| Planet-Tech | Planet-Forschungs-Card | Planet | `game/planet_evolution/planet_research.py` |
| Ascension | Ascension-Card | Planet | `game/planet_evolution/` (Ascension) |
| Verteidigung (später) | Defense-Card | Planet | `game/defense.py` |

Defense hat heute noch eine **Seiten-Queue-Liste** (`templates/defense.html`) — Angleichung optional nach GC-536E.

---

## Card-Anzeige (Ziel-UX)

Jede Card zeigt **höchstens einen** Queue-Block für dieses Item (aktiv oder nächster wartender Slot).

### Aktiv

```text
AKTIV
00:12:44
██████░░░░ 62%
```

### Wartend

```text
QUEUE #2
Startet in 00:12:44
```

```text
QUEUE #3
Startet in 00:27:10
```

- **Reihenfolge** über `queue_position` (1 = aktiv, ≥2 = wartend).
- **Cancel** bleibt an der Card (bestehende APIs).
- **Anreihen**-Button bleibt in der Card-Footer-Action.

Referenz-Pattern (Defense Job-Zeile, noch nicht pro Item-Card): `templates/defense.html` · Shipyard Job-Rows.

---

## Ticket-Kette (Etappen)

| Ticket | Titel | Scope |
|--------|-------|-------|
| **GC-536A** | Queue Card Contract | Globales Datenformat + Adapter + Tests |
| **GC-536B** | Building Cards | Oberes Bau-Queue-Panel entfernen; Status in Gebäude-Cards |
| **GC-536C** | Research Cards | Account-Forschung analog |
| **GC-536D** | Shipyard Cards | Schiffsbau in Schiff-Cards |
| **GC-536E** | Planet Evolution Cards | Planet-Tech + Ascension |

**Reihenfolge:** strikt A → B → C → D → E. Kein Ticket überspringen.

---

## GC-536A — Queue Card Contract

### Problem

Jede Domäne liefert Queue-Jobs mit leicht unterschiedlichen Feldnamen (`finish_time` vs `finish_at`, `remaining` vs `order_remaining`, …). Für einheitliche Card-UI braucht es **eine kanonische Job-Shape** und **Lookup pro Item-Key**.

### Kanonisches Job-Objekt (GC-536A ✅)

```json
{
  "owner_type": "building",
  "owner_key": "metal_mine",
  "job_id": 42,
  "status": "active",
  "queue_position": 1,
  "start_at": 1717590000.0,
  "finish_at": 1717590764.0,
  "duration_seconds": 1200,
  "remaining_seconds": 764,
  "progress_pct": 62,
  "label": "building_metal_mine",
  "target_level": 5
}
```

| Feld | Typ | Regeln |
|------|-----|--------|
| `status` | `"active"` \| `"queued"` | `queue_position == 1` → active |
| `queue_position` | int ≥ 1 | 1-basiert, Finish-Reihenfolge |
| `start_at` / `finish_at` | float (Unix s) | Server-authoritative |
| `remaining_seconds` | int ≥ 0 | `max(0, finish_at - now)` — nie negativ |
| `duration_seconds` | int ≥ 1 | Job-Dauer |
| `progress_pct` | int 0..100 | active: elapsed/duration clamp; queued/missing times: 0 |
| `target_level` / `target_amount` | int (optional) | Domänen-spezifisch |

**Owner:** `game/queue_card.py` — Presentation-Adapter only. Queue-Engine (`game/queue_engine.py`) bleibt Single Source of Truth für Finish/Scheduling.

### Akzeptanzkriterien (536A)

- [x] Normalizer liefert identische Shape für Build- und Research-Fixtures
- [x] `progress_pct` und `remaining_seconds` nie negativ; `queue_position` 1-basiert
- [x] Keine Änderung an Finish/Cancel/Reschedule-Logik ([QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md))
- [x] `pytest tests/test_queue_card_contract.py tests/test_queue_static_contract.py` grün
- [x] Bestehende Queue-Panels unverändert; `GC.renderCardQueueBlock` Stub, nicht produktiv verdrahtet

### Summary (unverändert nutzbar)

Bestehende `summary`-Blöcke bleiben für Header-Chips:

```json
{
  "count": 3,
  "limit": 3,
  "first_finish_in": 764,
  "has_queue": true
}
```

### Lookup-API (Server)

Neuer Owner: **`game/queue_card.py`** (CORE_ARCHITECTURE §17 — Presentation Adapter, keine zweite Queue-Engine).

```python
def normalize_card_queue_job(...) -> dict: ...
def compute_progress_pct(...) -> int: ...
def group_card_jobs_by_owner_key(jobs) -> dict[str, list]: ...
def card_queue_job_for_item(by_key, owner_key) -> dict | None: ...
def map_build_queue_to_card_jobs(build_queue, *, now=None) -> list: ...
def map_research_queue_to_card_jobs(research, *, now=None) -> list: ...
def map_shipyard_queue_to_card_jobs(shipyard_queue, *, now=None) -> list: ...
```

Adapter mappen vorhandene Client-Payloads — **keine DB-Mutation**, kein Scheduling.

| Domäne | Adapter | `owner_key` |
|--------|---------|-------------|
| Build | `map_build_queue_to_card_jobs` | `building_type` |
| Research | `map_research_queue_to_card_jobs` | `tech_key` |
| Shipyard | `map_shipyard_queue_to_card_jobs` | `ship_key` |
| Planet research | `map_planet_research_queue_to_card_jobs` | `tech_key` |
| Ascension | `map_ascension_queue_to_card_jobs` | `ascension_key` |

Quelle bleibt bestehende `*_for_client` / Status-Payloads — Adapter **lesen nur**.

### Game-State Erweiterung (optional, rückwärtskompatibel)

```json
{
  "build_queue": { "queue": [...], "summary": {...}, "by_item": { "metal_mine": [...] } },
  "research": { "...": "...", "queue_by_tech": { "energy_tech": [...] } }
}
```

Legacy-Felder (`queue`, `summary`, `active`) **bleiben** bis alle Etappen fertig sind.

### Frontend (536A ✅)

- `GC.renderCardQueueBlock(cardEl, queueJob)` in `static/main.js` — Stub, **nicht** an Pages angebunden
- Nutzt `formatEta` / `t()` — **keine** neue Queue-Math
- Bestehende Listen (`renderBuildQueue`, …) unverändert

### Betroffene Dateien (536A)

- `game/queue_card.py` ✅
- `tests/test_queue_card_contract.py` ✅
- `static/main.js` — Stub only ✅
- Docs ✅

Keine Hooks in `buildings.py` / `research.py` bis 536B+ (game-state enrichment optional dort).

---

## GC-536B — Building Cards ✅

### Problem

`/buildings` zeigte oben ein volles Queue-Panel. Spieler mussten zwischen Liste und Cards wechseln.

### Umsetzung

1. Kompakt-Header `#build-queue-compact` — Zähler only (`🏗 N Bauaufträge aktiv`)
2. Jede Gebäude-Card: `queue_job` aus `_attach_queue_jobs_to_panel_rows()` + `GC.renderCardQueueBlock`
3. Live-Update über `applyGameStateData` / `buildings_panel` Poll
4. Cancel in Card (`data-build-cancel-id`) — bestehende API

### Akzeptanzkriterien (536B)

- [x] Aktiver/wartender Bau in passender Gebäude-Card
- [x] Kein großes oberes Queue-Panel
- [x] Timer/Progress via Poll ohne Reload
- [x] Queue-Engine unverändert

---

## GC-536C — Research Cards ✅

### Umsetzung

1. Kompakt-Header `#research-queue-compact` — Zähler only
2. Tech-Cards: `queue_job` aus `_attach_queue_jobs_to_research_techs()` + generalisiertes `GC.renderCardQueueBlock`
3. Research-Akzent: `.gc-card-queue-block--research` (Scan/Core-Glyph)
4. Cancel in Card (`data-research-cancel-id`)

### Akzeptanzkriterien (536C)

- [x] Aktive/wartende Forschung in passender Tech-Card
- [x] Kein großes oberes Queue-Panel
- [x] Timer/Progress via Poll ohne Reload
- [x] Queue-Engine unverändert

---

## GC-536D — Shipyard Cards ✅

- Werft-Queue-Liste aus Seitenkopf in Schiff-Cards
- Batch-Jobs (amount > 1): `target_amount` + `ship_label_key` für Mengenzeile in der Card
- Kompaktstatus: `🚀 N Werftaufträge aktiv` (`#shipyard-queue-compact`)

Dateien: `game/shipyard.py`, `templates/shipyard.html`, `static/main.js`, `static/style.css`, `tests/test_shipyard_card_queue.py`.

Akzeptanz:
- [x] Aktiver Schiffsbau in passender Ship-Card (AKTIV, Menge×Typ, Timer, Progress)
- [x] Wartende Jobs mit QUEUE #n + „Startet in …“
- [x] Kein großes Queue-Panel als Haupt-UX
- [x] Poll/Card-Ticker ohne Reload
- [x] Queue-Engine unverändert

---

## GC-536E — Planet Evolution Cards ✅

### Umsetzung

1. Zwei getrennte Card-Owner: **Planet-Tech** (`planet_research` / `tech_key`) und **Ascension** (`ascension` / `ascension_key`)
2. Kompakt-Header: `🧬 N Planet-Tech-Aufträge`, `🌌 N Ascension-Aufträge` — kein großes Queue-Panel mehr
3. `queue_job` via `map_planet_research_queue_to_card_jobs` / `map_ascension_queue_to_card_jobs` + Attach in Dashboard/Status
4. Evo-Akzente: DNA-Scanline (Planet-Tech), Orbit-Pulse / Core-Ripple (Ascension); `prefers-reduced-motion`
5. Live: `refreshPlanetEvolutionState` → `applyPlanetEvolutionState` + Card-Ticker (kein Full-Reload)

Dateien: `game/queue_card.py`, `game/planet_evolution/planet_research.py`, `game/planet_evolution/ascension.py`, `game/planet_evolution/dashboard.py`, `templates/planet_evolution.html`, `static/main.js`, `static/style.css`, `tests/test_planet_evolution_card_queue.py`.

### Akzeptanzkriterien (536E)

- [x] Aktive Planet-Tech in passender Planet-Tech-Card (AKTIV, Zielstufe, Timer, Progress)
- [x] Wartende Planet-Techs mit QUEUE #n + „Startet in …“
- [x] Aktive Ascension in passender Ascension-Card (Phase/Ziel, Timer, Progress)
- [x] Kein großes Planet-Evo Queue-Panel als Haupt-UX
- [x] Poll/Card-Ticker ohne Reload
- [x] Queue-Engine unverändert

**GC-536 Epic:** A–E abgeschlossen (Build, Research, Shipyard, Planet-Evo/Ascension).

---

## Was sich **nicht** ändert

| Thema | Doc |
|-------|-----|
| Finish before mutate | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |
| Reschedule after cancel | GC-510 / GC-512 |
| Queue-Engine, Tabellen | `game/queue_engine.py` |
| `{ ok, state }` + `applyActionState` | [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) |
| Overview Aktivitäten (1 Zeile pro Kategorie) | `game/overview_page.py` |

GC-536 ist **Presentation-Layer** — kein Parallel-System (GC-000 Regel 15).

---

## Manuelle QA (nach jeder Etappe)

Erweiterung von [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md):

| ID | Check |
|----|-------|
| F1 | Card zeigt AKTIV mit Countdown + Progress für laufenden Job |
| F2 | Zweiter Job am selben Item: QUEUE #2 + „Startet in …“ |
| F3 | Cancel active → Card springt auf nächsten Job ohne Full Reload |
| F4 | PJAX Buildings → Research → zurück: Card-Timer konsistent |
| F5 | Shell-Zähler (falls sichtbar) = `summary.count` |

---

## Priorisierung

Nach **GC-611** Fleet Close-Out (siehe [ROADMAP.md](ROADMAP.md)):

```text
GC-611 → GC-536A → GC-536B → GC-536C → GC-536D → GC-536E
```

Begründung: Completion-First (Fleet/Galaxy QA) vor UX-Epic; 536A legt Contract, B–E sind unabhängig reviewbare UI-Tickets.
