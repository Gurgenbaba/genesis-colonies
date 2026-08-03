# GC-563 — Command Map MVP

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **S** — nächster Schritt nach GC-560  
> **Status:** ✅ umgesetzt  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-560 ✅ (Empire Identity Layer)

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Identity-Basis: [GC-560_EMPIRE_IDENTITY_LAYER.md](GC-560_EMPIRE_IDENTITY_LAYER.md)

---

## Leitplanke (für Cursor)

> **`/galaxy?view=command_map`** (Alias: `view=imperium`) ist der **einzige Zielort** für die Command Map.  
> **`/empire` nicht anfassen.** Klassische **`/galaxy` Systemansicht nicht entfernen.**  
> Imperium-View von **Liste → visuelle Map** weiterentwickeln — keine parallele Route, kein neues Backend-System.

---

## Implementierungsreihenfolge (bindend)

```text
1. Erst command_map.py bauen        → build_command_map_payload(), Layout + Kanten
2. Dann Template-Partial rendern      → galaxy_command_map_panel.html (Graph, kein Listen-Hauptgefühl)
3. Dann CSS/JS minimal              → Hub/Spoke/Linien; JS nur für SVG-Resize / Planet-Switch
4. Dann Tests                       → tests/test_command_map.py
5. /empire und klassische /galaxy nicht anfassen
```

Keine Umkehrung: **kein CSS/Template vor Server-Payload.**

---

## Test-Scope (nicht GC-563)

Der bekannte Failure `test_api_planets_active_switch_returns_fresh_colony_resources` mit `coordinate_occupied` ist **nicht Teil von GC-563**.

**Nicht** im Rahmen dieses Tickets fixen — außer der neue Code verursacht ihn reproduzierbar.

GC-563 Tests: `tests/test_command_map.py` + Regression `tests/test_empire_identity.py`.

---

## Product-Rationale

GC-560 liefert Identität (Genesis Ark, Rollen, Header). Spieler sehen heute noch eine **Liste**:

```text
🏛 Genesis Ark
⛏ Vega Prime
🔬 Helios Gate
⚓ Titan Forge
```

GC-563 macht daraus eine **Imperiumskarte**:

```text
        🔬 Helios Gate

⛏ Vega Prime —— 🏛 Genesis Ark —— ⚓ Titan Forge

        🛡 Aegis Bastion
```

Der Spieler soll **sein Sternenreich sehen** — nicht nur Kolonienamen scrollen.

**Keine neue Mechanik:** Keine Regionen, Evo-Gates, Einflusszonen, Chokepoints (GC-564+). Nur Darstellung.

---

## Architektur-Kontext

```text
/empire                          = Wirtschaft, Produktion, Matrix (TABU)
/galaxy                          = Klassische Systemansicht (TABU entfernen)
/galaxy?view=command_map         = Command Map (dieses Ticket)
```

Tabs auf `/galaxy` bleiben:

```text
[ Command Map ] [ Klassische Galaxy ]
```

---

## Problem

| Heute (GC-560) | Ziel (GC-563) |
|----------------|---------------|
| Vertikale Liste in `galaxy_command_map_panel.html` | Visueller Graph mit Hub + Satelliten |
| Keine räumliche Beziehung | Genesis Ark im Zentrum, Kolonien drumherum |
| Trade Routes unsichtbar | Aktive `planet_trade_routes` als Verbindungslinien |
| Identität vorhanden | Identität **räumlich** erfahrbar |

---

## Zielbild

### Layout (MVP)

- **Hub:** Homeworld (`is_homeworld`) immer zentral, größer, 🏛
- **Satelliten:** Nicht-Homeworld-Kolonien um den Hub — Position aus **serverseitigem Layout** (kein Frontend-Math)
- **Kanten:** Aktive Handelsrouten (`planet_trade_routes`) als gestrichelte Linien zwischen Knoten
- **Ohne Trade Route:** Einfache Hub→Kolonie-Linie (optional, dezent) oder nur Satelliten-Placement ohne Kante

Beispiel-Placement-Heuristik (Server):

| Rolle | Slot-Position (relativ zum Hub) |
|-------|----------------------------------|
| `mining` | links |
| `research` | oben |
| `shipyard` | rechts |
| `fortress` | unten |
| `trade` / `frontier` / `general` | verbleibende Quadranten |

Mehrere Kolonien gleicher Rolle: leicht versetzt entlang der Achse (index-basiert).

### Knoten-Inhalt

Jeder Knoten zeigt (aus GC-560 Payload):

- Icon (`empire_role_icon`)
- Name
- Rolle (Label-Key → `T()`)
- Aktiv-Markierung (`is_active`)
- Klick → `POST /api/planets/active` (bestehend, `data-empire-identity-switch`)

Koordinaten `[G:S:P]` sekundär (Tooltip oder klein unter Name) — nicht primär.

### Visuell

- Dunkler Panel-Hintergrund (bestehende `--gc-*` Tokens)
- SVG-Overlay oder CSS-Grid + absolute Position für Kanten
- **Kein** Canvas/WebGL, **kein** D3-Import — MVP mit SSR + CSS/SVG
- Responsive: Mobile stapelt/komprimiert, Desktop Hub-and-Spoke

Referenz-Richtung (Mockup): [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — **keine** 1:1-Pixel-Spec.

---

## Explizit NICHT in GC-563

| Verboten | Ticket |
|----------|--------|
| `/empire` anfassen | — |
| Klassische Galaxy-Slots entfernen/umbauen | — |
| Regionen, Einflusszonen, Chokepoints | GC-564–566 |
| Evolution Unlock Gates | GC-562 |
| Neue DB-Tabellen / Migration | — |
| Neue REST-Routes (optional Layout-JSON später) | SSR-Payload reicht |
| Frontend-Layout-Algorithmus (Regel 16) | Server liefert `x/y` oder Slot-Key |
| 1:1 Mockup-Pixelkopie | — |
| Gameplay-Boni | — |

---

## Technische Leitplanken

- **Owner Layout:** `game/planet_evolution/command_map.py` (neu) — Graph-Payload aus `empire_identity` + Trade Routes
- **Reuse:** `build_colonies_identity()` aus `empire_identity.py` — nicht duplizieren
- **Trade Routes:** `get_trade_routes()` — Kanten nur für `is_active = 1`
- **PJAX:** Map in `galaxy_command_map_panel.html` SSR; Planet-Switch wie GC-560
- **Kein** `location.reload()`

---

## API / SSR-Contract (Erweiterung)

Kein neuer Endpoint. `galaxy_view` übergibt erweitertes Payload:

```python
command_map = {
    "nodes": [
        {
            "planet_id": 1,
            "name": "Genesis Ark",
            "empire_role_key": "homeworld",
            "empire_role_icon": "🏛",
            "identity_title_key": "empire_homeworld_subtitle",
            "is_active": True,
            "is_homeworld": True,
            "layout_slot": "hub",       # hub | north | south | east | west | ...
            "layout_index": 0,          # offset bei mehreren im gleichen Slot
        },
        ...
    ],
    "edges": [
        {
            "source_planet_id": 1,
            "target_planet_id": 2,
            "edge_type": "trade_route",  # trade_route | hub_link
            "resource_key": "metal",     # optional, aus route
        },
        ...
    ],
}
```

Frontend rendert nur `nodes[]` + `edges[]` — **keine** Positionsberechnung in JS.

---

## Betroffene Dateien

**Kern:**

- `game/planet_evolution/command_map.py` — **neu:** `build_command_map_payload(player_id, conn)`
- `app.py` — `galaxy_view` bei `view=command_map`: `command_map` statt nur `colonies_identity` (oder beides: map enthält nodes)
- `templates/partials/galaxy_command_map_panel.html` — Liste → Graph-Markup (SVG + Knoten)
- `static/style.css` — Command-Map-Graph, Knoten, Kanten, Hub-Größe
- `static/main.js` — `initGalaxy()`: ggf. Resize-safe SVG-Linien nachzeichnen; Planet-Switch unverändert

**Optional:**

- `locales/de.json`, `locales/en.json` — Map-spezifische Hints (`galaxy_command_map_graph_hint`)

**Tests:**

- `tests/test_command_map.py` — **neu:** Layout-Slots, Kanten aus Trade Routes, Hub zentral

**Nicht bearbeiten:**

- `templates/empire.html`, `game/empire_page.py`
- Klassische Galaxy-Slot-Markup in `galaxy.html` (else-Zweig)
- `game/galaxy.py` Koordinatenmodell
- Fleet / Queue

---

## Anforderungen

1. **`build_command_map_payload()`** liefert `nodes` + `edges` pytest-deckbar.
2. Homeworld ist immer `layout_slot: hub`, visuell zentral und hervorgehoben.
3. Kolonien erscheinen als Satelliten-Knoten mit GC-560-Rollen (Icon, Name, Label).
4. Aktive Handelsrouten erscheinen als sichtbare Verbindungen zwischen Knoten.
5. Klick auf Knoten wechselt active planet (bestehendes API, kein Reload).
6. Liste aus GC-560 wird durch Graph ersetzt (kein Listen-Fallback nötig, außer `prefers-reduced-motion`/A11y optional kompakte Liste als `aria`-Fallback).
7. Klassische Galaxy-Tab und -Ansicht unverändert funktional.
8. `/empire` unverändert.

---

## Akzeptanzkriterien

### Haupt-Akzeptanztest

`/galaxy?view=command_map` zeigt **keine Liste mehr als Hauptgefühl**, sondern:

```text
Genesis Ark als Hub (zentral)
Kolonien als Spokes (um den Hub)
Routen als Linien (Trade Routes)
Rollen als Icons (GC-560)
```

Wenn das sitzt, ist es der **erste echte sichtbare Schritt** zur neuen Galaxy.

### Checkliste

- [ ] `/galaxy?view=command_map` — Hub-and-Spoke-Graph, nicht vertikale Liste als primäre UI
- [ ] Genesis Ark (Homeworld) zentral; Kolonien mit Rollen-Icons als Spokes
- [ ] Mindestens eine Trade-Route zwischen zwei Kolonien → sichtbare Kante im Test-Setup
- [ ] Planet-Klick aktualisiert Header Switcher ohne Reload
- [ ] `/galaxy` (klassisch) und `/empire` ohne Regression
- [ ] Layout-Slots **serverseitig** — kein Layout-Algorithmus in `main.js`
- [ ] `pytest tests/test_command_map.py tests/test_empire_identity.py -v` grün
- [ ] `test_api_planets_active_switch_returns_fresh_colony_resources` — **out of scope** (Flake)

### Manuelle QA (90 Sekunden)

1. Login → Galaxy → Tab **Command Map**
2. Hub (Genesis Ark) in der Mitte, Kolonien verteilt
3. Trade Route zwischen zwei Kolonien → Linie sichtbar
4. Kolonie anklicken → Header + active state wechseln
5. Tab **Klassische Galaxy** → System-Slots wie bisher
6. `/empire` → nur Produktion/Matrix, keine Map

---

## Referenz-Docs

- [ ] [IMPERIUM_VISION.md](IMPERIUM_VISION.md)
- [ ] [GC-560_EMPIRE_IDENTITY_LAYER.md](GC-560_EMPIRE_IDENTITY_LAYER.md)
- [ ] [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)
- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regel 16 (keine Frontend-Mechanik)
- [ ] [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)

---

## Nachfolger

| Ticket | Fokus |
|--------|-------|
| **GC-562** | Evolution Unlock Gates (Level → Orte) |
| **GC-564** | Regions & Sectors (Genesis Core, Outer Rim, …) |
| **GC-565** | Chokepoints |
| **GC-566** | Influence System (Territorien visualisieren) |

---

## Ausgabe (nach Abschluss)

### Root Cause

### Changed Files

### Tests

### Ergebnis

---

## Player Article

```yaml
---
codex_id: command_map
band: II
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - galaxy_view
  - empire_view
related_codex:
  - galaxy
  - expansion
  - planet_evolution
  - strategic_worlds
  - fleet
terminology: GENESIS_TERMINOLOGY
unlock:
  type: homeworld_level
  value: 5
teaser_key: codex_unlock_command_map_teaser
---
```

## Quick Help

Die **Command Map** (Weltkarte) zeigt dein Imperium räumlich: Genesis Ark als Hub, Kolonien, Expansion Sites und strategische Orte — unter `/galaxy` als Weltkarte-Tab (`view=command_map`).

## Summary

Die **Command Map** ist die visuelle Imperiumskarte von Genesis Colonies. Statt einer reinen Kolonie-Liste siehst du Hub-and-Spoke: die **Genesis Ark** im Zentrum, verbundene Welten, Handelsrouten und Orte mit Typ und Versprechen. Sie lebt unter **`/galaxy`** (Weltkarte) — **`/empire` ist keine Karte**, sondern Wirtschafts-/Produktionsmatrix.

## Why

Ein Sternenreich soll man **sehen**, nicht nur scrollen. Die Command Map macht Expansion, Rollen und Ziele räumlich lesbar und verbindet Planet Evolution, Expansion Sites und Flottenziele zu einer gemeinsamen Weltansicht.

## How it works

- Öffne **`/galaxy`** und den Tab **Weltkarte** (`view=command_map` / Alias `imperium`).
- **Hub:** Genesis Ark (Homeworld) zentral; Kolonien als Satelliten mit Rollen-Icons.
- **Kanten:** aktive Handelsrouten und Hub-Links verbinden Welten.
- Klick auf eigene Welten wechselt den **aktiven Planeten** (wie Header-Switcher).
- Expansion Sites, Strategic Worlds, Landmarken und Chokepoints erscheinen mit Entwicklungsfortschritt der Ark — Aktionen hängen an Gates und Missionen.
- Klassische **Systemansicht** (`view=system`) bleibt parallel für Slots und Flotten-Prefill.
- **`/empire`** nicht mit der Command Map verwechseln.

## Related Systems

- galaxy
- expansion
- planet_evolution
- strategic_worlds
- fleet
- genesis_ark

## Commander Tips

- Expansion und Orte zuerst auf der **Weltkarte** planen, nicht nur in der Slot-Liste.
- Genesis Ark bleibt der Hub — Kolonien drumherum lesen.
- `/empire` = Produktion/Matrix; Weltkarte = `/galaxy` Weltkarte-Tab.

## FAQ

**Wo finde ich die Command Map?**
Unter `/galaxy` → Tab **Weltkarte** (`view=command_map`). Nicht unter `/empire`.

**Unterschied zu `/empire`?**
Command Map = räumliche Imperiums-/Weltansicht. `/empire` = Wirtschafts- und Produktionsmatrix.

**Brauche ich die Systemansicht noch?**
Ja — klassische Slots, Expeditions-Slot und viele Flotten-Prefills laufen weiter über die Systemansicht.

## Discord Summary

**Command Map — Imperium auf der Weltkarte**

`/galaxy` Weltkarte: Genesis Ark als Hub, Kolonien, Expansion Sites, Strategic Worlds. `/empire` ist Wirtschaft, keine Karte. Freischaltung mit Ark-Entwicklungsstufe 5.
