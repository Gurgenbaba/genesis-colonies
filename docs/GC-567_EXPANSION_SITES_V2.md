# GC-567 — Expansion Sites v2 (Presentation)

> **Epic:** EPIC-15 · **Status:** ✅ Implementiert · **Stand:** 2026-06-12

Expansion Sites sind Orte mit Typ, Versprechen, Risiko, Belohnungs-Hint und Zukunftsrolle — rein visuell, kein Gameplay.

## Owner

- `game/planet_evolution/expansion_gates.py` — Site-Metadaten + Payload
- `templates/partials/galaxy_command_map_panel.html` — Inspector + Site-Nodes
- `static/main.js` — `initCommandMapSiteInspector()`
- `tests/test_expansion_sites_v2.py`

## Akzeptanz

- [x] Site-Metadaten in Payload und Nodes
- [x] Inspector mit Name, Status, Level, Region, Risiko, Versprechen, Belohnung, Zukunft
- [x] Locked Sites zeigen Versprechen statt nur „Gesperrt“
- [x] Keine Gameplay-Boni
