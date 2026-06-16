# GC-620F — Test Contract Sync (post GC-591–597)

**Status:** ✅ Cluster 1 Fuel / Queue / Locale / Static-Live / Placeholder (38 Tests) · ✅ Cluster 2 Galaxy / Command Map (131 Tests) · ✅ Cluster 3 Remaining Fullsuite (14 Tests)  
**Voraussetzung:** [GC-620 Full Alpha Readiness Audit](GC-620_FULL_ALPHA_READINESS_AUDIT.md)  
**Folge-Tickets:** GC-621 (First 30 Min QA), GC-620B (Locale), GC-SEC-P0

---

## Ziel

Aus:

```text
1366 passed / 37 failed
```

machen:

```text
≥ 1395 passed / ≤ 5 failed
```

**Ohne eine einzige Gameplay-Regel zu ändern.**

---

## Scope (hart)

### Erlaubt

```text
tests/
locales/          (nur wenn test_locale_keys eindeutig fehlenden Key beweist)
docs/GC-620F_*    (dieses Ticket)
```

### Verboten

```text
game/
static/
templates/
app.py
```

Ausnahme: Keine. PlayerCard DB-Lock → **GC-620C** (game/).

---

## Cluster

### 1. Galaxy / Command Map (~16) ✅

Nach GC-590B, GC-591–597C: Sidebar entfernt, World Inspector Modal, Full Map Layout, Discovery im Modal.

**Contract-Sync (Cluster 2):**
- Klassische Galaxy-Ansicht: HTTP-Tests mit `view=system` (Default ist `command_map`)
- Command Map: `galaxy-command-map-graph--fullmap`, `gc-world-inspector-modal`, Node-Marker (`data-world-field-inspect`, `data-strategic-*`, `data-landmark-inspect`)
- Kein rechtes Sidebar/HUD: `gc-command-center-hud` negativ assertiert
- Location Actions: Node-Datasets + World Inspector Modal JS (`openWorldInspectorFromNode`, `mergeWorldFieldPayload`)

Betroffene Tests u.a.:

- `test_galaxy.py` (fleet shortcuts, prefill contract)
- `test_gc582c`, `test_gc582f`, `test_gc583*`, `test_gc584`, `test_gc592`, `test_gc594`
- `test_imperium_regions`, `test_region_landmarks`, `test_strategic_worlds`

### 2. Queue / Static Live (~9) ✅ (Cluster 1)

Nach GC-557A–D: `syncServerClockFromState()`, `GC.serverNow()`, `data-timer-kind`.

- `test_static_live_updates.py` (4)
- `test_queue_card_global_ux.py` (4)
- `test_queue_static_contract.py` (1)

### 3. Fuel / Exchange (~4) ✅ (Cluster 1)

- `test_fuel_cells_resource_bar.py` (2)
- `test_fuel_exchange.py` (2)

### 4. Locale / Nav / Misc (~5) ✅ (Cluster 1)

- `test_locale_keys.py`
- `test_placeholder_nav.py` (2)
- `test_persistence.py`
- `test_planet_evolution_dashboard.py`

### 5. Remaining Fullsuite (Cluster 3) ✅

Nach Cluster 1+2+C: verbleibende Drift in Persistence, PE-Template, Research-Timer.

**Contract-Sync (Cluster 3):**
- `test_persistence.py::test_legacy_planets_migration_idempotent` — Legacy-Seed ohne `planet_buildings` (init_db legt volle Tabelle an); `init_db()` + `migrate.py` idempotent
- `test_planet_evolution_dashboard.py` — `tech.icon_fallback` + `gc-card-queue-glyph` statt `job.icon` (GC-536 Queue-Cards)
- `test_gc804_research_timer.py` — `gc-card-queue-timer` + Toleranz ±2s (SSR-Timer, kein `research_queue` span)

### 6. Bewusst offen (GC-620C) ✅

- `test_playercard_rank_survives_operational_error` — in **GC-620C** gefixt (`game/ranking.py`)

---

## Abnahme

```bash
python -m pytest tests/ -q --tb=no
# Ziel: ≥ 1395 passed, ≤ 5 failed
```

Gezielt vor Merge:

```bash
python -m pytest tests/test_static_live_updates.py tests/test_galaxy.py tests/test_placeholder_nav.py -q
```

---

## No-Gos

- Kein Feature
- Kein Refactor in game/static/templates
- Kein „Test abschwächen“ ohne Begründung im Commit/Doc
- Locale-Gameplay-Texte (Attack-Hint etc.) → **GC-620B**, nicht dieses Ticket
