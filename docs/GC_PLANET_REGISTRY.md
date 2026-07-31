# GC-575 — Planet Registry (Imperiumsübersicht)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** S — größter UX-Hebel für Multi-Kolonie  
> **Status:** ✅ GC-575A MVP umgesetzt · ✅ GC-PLANET-UI-001 Status Indicators (Gebäude/Forschung/Werft/Verteidigung) · Folge 575B–E Backlog  
> **Stand:** 2026-07-29

Design-Richtung: OGameX-Prinzip (alle Welten sichtbar, 1 Klick) — **nicht** kopieren, sondern Genesis: Rollen, PE-Identität, Imperiumsgefühl.

---

## Entscheidungen (verbindlich)

| Entscheidung | Festlegung |
|--------------|------------|
| Shell | **4 Spalten:** Left Nav · Main · Meta-Nav · Planet Registry (rechts außen) |
| Wechsel | 1 Klick auf Mini-Card → `POST /api/planets/active` |
| Header | **Kein** Planet-Switcher / kein Header-Fallback (Desktop + Mobile) |
| Mobile / Tablet | Rechter Drawer stapelt Meta + Registry |
| `/empire` | Unangetastet (Wirtschaftsmatrix) |
| Parallel-Systeme | Verboten — Owner: `empire_identity`, `_planet_switcher_row`, `get_context_planet` |

---

## Shell-Vertrag (GC-806 Erweiterung)

```text
Left Sidebar (Gameplay) | Main (#main-content) | Meta (#gc-sidebar-nav-right) | Imperium (#gc-planet-registry)
Header: kein Planet-Switcher
```

- Outer rail: `.gc-sidebar-right-rails` — Desktop `display: contents` → 4 Spalten; Tablet-Drawer stapelt Meta+Registry
- Registry: `#gc-planet-registry` (Desktop/Tablet rechte Spalte); Phone: `#gc-planet-registry-sheet` / `#gc-sheet-planet-registry` (Header-Pfeil)
- Phone META/MEHR: keine Planetenliste (nur Meta-Nav-Links)
- Meta-Nav: `#gc-sidebar-nav-right` eigene Spalte (wie vor GC-575), nicht unter Registry gestapelt
- Planet-Limit: Registry-Header (`data-planet-limit-value`), nicht Header-Dropdown
- Shell: zentrierte Max-Width (`--gc-shell-max-width: 1500px`); schmale Imperium-Spalte (`--gc-registry-rail-w: 196px`)

---

## Ticket-Kette

| Ticket | Scope | Status |
|--------|--------|--------|
| **GC-575** | Spec + Shell-Vertrag (dieses Doc) | ✅ |
| **GC-575A** | MVP: Mini-Cards + 1-Klick-Switch; Header-Switcher entfernen; 4-Spalten-Shell | ✅ |
| **GC-PLANET-UI-001** | Planet Status Indicators neben Koordinaten (`status_indicators[]`: Gebäude, Forschung, Werft, Verteidigung) | ✅ |
| **GC-575B** | Eine Server-Statuszeile (Warnung > Lager% > Energie) — separat von Aktivitäts-Indikatoren | 📋 |
| **GC-575C** | Sortierung / Rollengruppen / Akzentfarben | 📋 |
| **GC-575D** | Hover-Panel + Kontextmenü | 📋 |
| **GC-575E** | Suche (30+) + PE-Klassen-/Herocard-Thumbs | 📋 |

---

## Owner (erweitern, nicht duplizieren)

| Layer | Owner |
|-------|--------|
| Rollen / Icons | `game/planet_evolution/empire_identity.py` |
| List-Payload | `list_player_planets_for_switcher` / `_planet_switcher_row` |
| Status Indicators | `list_player_planets` + Batch-Helper (`buildings` / `research` / `shipyard_queue` / `defense`) → `status_indicators[]` |
| Switch API | `POST /api/planets/active` → `set_active_planet` |
| UI Template | `templates/partials/planet_registry.html` + `sidebar_right.html` |
| Client | `static/main.js` — `initPlanetRegistry`, `rebuildPlanetRegistry`, `GC.updatePlanetRegistryFromState` |
| Poll slice | bestehende `planets[]` in diet `/api/game-state` (inkl. `status_indicators`) |

---

## GC-575A MVP — In Scope

- Permanente Mini-Karten: runder Herocard-Thumb (wie Galaxy-Ring), Name, Identity/Rolle, Koordinaten, `is-active`
- 1-Klick-Wechsel inkl. soft PJAX (bestehender Switch-Flow)
- Header-Switcher-Template/CSS/JS entfernen
- Meta-Nav als eigene Spalte (nicht unter Registry gestapelt)
- Tests: Registry SSR, kein Header-Switcher, API-Contract unverändert

## Explizit NICHT in GC-575A

Hover-Tooltip, Kontextmenü, Suche, Rollenfarben, Warn-Icons, PE-Vorschaubilder, Sortierung nach Rolle, Produktions-/Lager-Zeile, Full-`empire_page`-Snapshots im diet poll.

---

## GC-PLANET-UI-001 — Planet Status Indicators

Erweiterbare Aktivitäts-Icons **rechts neben den Koordinaten** (nicht die GC-575B Ressourcen-/Warn-Zeile).

### Payload-Vertrag

Jedes `planets[]` / `HEADER_PLANETS`-Row:

```python
"status_indicators": [
  {"key": "building", "icon": "🏗", "label_key": "planet_status_building_active"},
  {"key": "research", "icon": "🔬", "label_key": "planet_status_research_active"},
  {"key": "shipyard", "icon": "⚓", "label_key": "planet_status_shipyard_active"},
  {"key": "defense", "icon": "🛡", "label_key": "planet_status_defense_active"},
]
```

- `[]` wenn nichts aktiv; Reihenfolge: building → research → shipyard → defense
- Server authority: Client rendert nur `icon` + `T(label_key)` — keine Queue-Formel im Frontend
- Diet-Poll: Key `status_indicators` in `_PLANET_SWITCHER_POLL_KEYS`
- `building` / `shipyard` / `defense`: Planet hat nicht abgelaufenen Queue-Job
- `research`: Account-Queue aktiv → Icon am **Kontext-/Aktiv-Planeten** (wie Command Center `research_applies`)
- UI: `.gc-planet-registry-card-meta` → coord + `.gc-planet-registry-card-status` (mehrere Icons in Reihe)

Spätere Keys (`fleet`, Attack, Mail, PE, …) hängen dieselbe Liste an — kein UI-Umbau.

---

## Verbote (GC-000)

- Kein zweites Planet-Scope / Session-Planet
- Keine Frontend-Produktions-/Lager-Formel
- Kein `location.reload()` beim Wechsel
- Kein paralleles Header-Dropdown „zur Sicherheit“
- Meta-Nav nicht löschen
- Keine neuen globalen `.gc-card-*` / Queue-Layout-Änderungen

---

## Docs / Tests

- [PLANET_SCOPE.md](PLANET_SCOPE.md) — Registry statt Header-Switcher
- [ARCHITECTURE.md](ARCHITECTURE.md) / [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — 4-Spalten-Shell
- [STATE_AJAX.md](STATE_AJAX.md) — `planets[]` Consumer = Registry
- Tests: `tests/test_planet_registry.py`

---

## Nachfolger

GC-561 (PlayerCard / weitere Surfaces) bleibt separat. Registry ist die Shell-Surface für Imperiums-Kolonien; GC-561 erweitert andere Surfaces, nicht den Switch-Owner.
