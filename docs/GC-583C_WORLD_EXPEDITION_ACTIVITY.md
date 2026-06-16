# GC-583C — World Expedition Activity

> **Epic:** EPIC-15 · **Status:** ✅ · **Stand:** 2026-06-13  
> **Voraussetzung:** GC-583A ✅ · GC-583B ✅

Live expedition status on world-map fields — derived from `fleet_movements` + recent `player_messages`. No new tables.

## Status values

| `expedition_status` | Source |
|---------------------|--------|
| `idle` | default |
| `expedition_active` | fleet outbound + `world_key` |
| `expedition_returning` | fleet returning + `world_key` |
| `recently_reported` | expedition message ≤ 48h (if no active fleet) |

Classic slot-16 expeditions do **not** annotate world fields.

## Owner

- Activity map: `game/planet_evolution/world_expedition_activity.py`
- Payload attach: `game/planet_evolution/world_map.py`
- UI: command map template + `static/main.js`
