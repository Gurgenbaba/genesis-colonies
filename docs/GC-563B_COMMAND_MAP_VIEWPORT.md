# GC-563B — Command Map Viewport (Pan & Zoom)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** M — nach GC-562A, vor GC-564  
> **Status:** ✅ erledigt  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-563 ✅ · GC-562 ✅ · GC-562A ✅

---

## Problem

Die Command Map ist heute ein **festes Hub-and-Spoke-Viewport** (100×100 %). Mit vielen Kolonien + Expansion Sites passen Knoten nicht mehr ins sichtbare Feld — Navigation fehlt.

---

## Scope (MVP)

### Rein

1. **Pan** — Drag / Pfeiltasten / Touch-Scroll auf `#galaxy-command-map-graph`
2. **Zoom** — Mausrad + Buttons (Fit all / Reset)
3. **Fit-to-graph** — initial alle Nodes sichtbar (Bounding-Box aus Server-Layout)
4. **PJAX-safe** — `GC.registerCleanup()` beim Verlassen der Galaxy-Seite
5. **Keine Server-Logik** — reines UI auf bestehendem `command_map` Payload

### Explizit nicht (eigene Tickets)

| Wunsch | Ticket / Begründung |
|--------|---------------------|
| **Alle anderen Spieler** auf der Command Map | **Nicht Imperiums-Map** — siehe unten |
| Regionen-Polygone | GC-564 |
| Koordinaten-Galaxy ersetzen | Verboten (IMPERIUM_VISION) |

---

## „Alle anwesenden Spieler“ — Klärung

Die **Command Map** ist laut [IMPERIUM_VISION.md](IMPERIUM_VISION.md) die **eigene Reichskarte** (Genesis Ark + Kolonien + freigeschaltete Sites).

**Fremde Spieler / Galaxy-Präsenz** gehören in:

- klassische **`/galaxy?view=system`** (Koordinaten, Fleet, Kolonisierung)
- später **GC-566 Influence** / **GC-568 Territorial Warfare** (Territorium, nicht Hub-and-Spoke)

Optional später: **GC-569 Galaxy Presence Layer** — dezente Fremd-Marker in der Systemansicht oder als separater Overlay-Tab, **nicht** als Ersatz für die Imperiums-Command-Map.

---

## Technik

- **Owner UI:** `static/main.js` — `initCommandMapViewport()`
- **Markup:** `galaxy_command_map_panel.html` — innerer `.galaxy-command-map-canvas` Wrapper
- **CSS:** transform auf Canvas, Zoom-Controls unten rechts
- **State:** sessionStorage optional für zoom/pan (nice-to-have)

---

## Akzeptanz

- [x] Pan per Drag auf Viewport
- [x] Zoom per Mausrad + Pinch (Touch)
- [x] Reset „Zentrum“ → Genesis Ark
- [x] sessionStorage hält Zoom/Position über Planetwechsel & PJAX
- [x] Planet-Switch blockiert nicht nach Pan (wasDragging)
- [x] Tests: Template + main.js Smoke

---

## Reihenfolge EPIC-15 (aktualisiert)

```text
GC-562  Evolution Gates        ✅
GC-562A Polish                 ✅
GC-563B Viewport Pan/Zoom      ✅
GC-564  Regions & Sectors
```

---

## Root Cause

Hub-and-Spoke skaliert nicht visuell — ohne Viewport wird die Map bei vielen Kolonien + Expansion Sites unbenutzbar.

## Changed Files

- `templates/partials/galaxy_command_map_panel.html` — Viewport/Canvas/Reset-Button
- `static/main.js` — `initCommandMapViewport()`, sessionStorage, PJAX cleanup
- `static/style.css` — Viewport/Canvas/Controls
- `locales/de.json`, `locales/en.json`
- `tests/test_command_map_viewport.py` — neu
- `tests/test_command_map.py` — Viewport-Marker
- `docs/GC-563B_COMMAND_MAP_VIEWPORT.md`, `docs/ROADMAP.md`

## Tests

`pytest tests/test_command_map_viewport.py tests/test_command_map.py -q` → 8 passed

## Ergebnis

Command Map ist pan-/zoom-fähig; Zentrum springt auf Genesis Ark; Zoom/Position bleiben über Planetwechsel in `sessionStorage` erhalten.
