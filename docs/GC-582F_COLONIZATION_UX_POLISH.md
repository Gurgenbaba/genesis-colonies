# GC-582F — Colonization UX Polish

> **Epic:** EPIC-15 · **Status:** ✅ · **Stand:** 2026-06-13

Presentation-only polish for the world-map colonization loop. No boni, no EffectResolver, no schema changes.

## Scope

| In | Out |
|----|-----|
| World colonize fleet reports (name, type, world_key) | Role boni (582E) |
| Map badge „Neu kolonisiert“ (7d window) | New colonize backend |
| Colony panel „Kolonie öffnen“ + Herkunft | `/empire`, classic galaxy |
| Foreign world colony inspector | |

## Owner

- Reports: `game/planet_evolution/world_colonization.py` → `build_world_colonize_report`
- Fleet hook: `game/fleet.py`
- Map payload: `game/planet_evolution/command_map.py`
- UI: `templates/partials/galaxy_command_map_panel.html`, `static/main.js`
