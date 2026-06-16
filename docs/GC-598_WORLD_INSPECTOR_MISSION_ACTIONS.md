# GC-598 — World Inspector Mission Actions MVP

**Status:** ✅ MVP  
**Owner:** `game/planet_evolution/command_center.py`, `static/main.js`

## Ziel

World Inspector wird handlungsfähig: passende Mission-Buttons öffnen den bestehenden Fleet-/Galaxy-Pfad mit Prefill — **keine neue Mission-Engine**.

## Payload

Command-Center-Snapshots liefern `mission_actions[]`:

```json
{
  "action_key": "spy",
  "mission": "spy",
  "label_key": "fleet_mission_spy",
  "enabled": true,
  "blocked_reason_key": "",
  "href": "/fleet?mission=spy&world_key=…&target_planet_id=…&target_type=enemy_colony",
  "world_key": "field:mining:…",
  "planet_id": 42,
  "target_type": "enemy_colony"
}
```

## Mission × Zieltyp

| Ziel | Missionen |
|------|-----------|
| Fremde Kolonie / Foreign Empire | Spionage, Angriff |
| Eigene Kolonie | Transport, Deploy, Sammeln |
| Expedition World | Expedition |
| Wreckage / Salvage | Bergung (`mission=expedition`, `target_type=wreckage`) |
| Kolonialisierbarer Ort | Kolonisieren |

## UI

- `appendMissionActions()` rendert Buttons aus `mission_actions`
- Disabled + `title` aus `blocked_reason_key` (z. B. `no_expedition_ships`, Kolonie-Limit)
- Foreign nodes mit `mission_actions` → `renderForeignMissionModal` (kein GC-597E DEV-Fallback)
- Klick → `GC.navigateTo(href)` (Server-generierter Fleet-Prefill)

## Tests

`tests/test_gc598_world_inspector_mission_actions.py`
