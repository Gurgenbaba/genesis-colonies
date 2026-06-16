# GC-590A — World Native Fleet Target Model

**Status:** Backend (590A) — Fleet UI coords strip remains until GC-590B.

## Ziel

> Flotten fliegen nicht mehr zu Koordinaten. Flotten fliegen zu Orten.

## Scope (590A)

- `game/fleet_target.py` — normalization + `world_target` response block
- `build_fleet_send_preview` / `send_fleet` / `POST|GET /api/fleet/resolve-target` accept world-native fields
- Legacy G:S:P remains internal adapter (Regel 15 — no parallel fleet system)

## API

### Request (priority)

1. `target_planet_id`
2. `world_key` / `target_world_key`
3. `target_world_x` + `target_world_y`
4. `target_galaxy` + `target_system` + `target_position`

Optional: `target_type` ∈ `planet`, `world_colony`, `expedition_world`, `anomaly`, `wreckage`, `enemy_colony`.

### Response (`target.world_target`)

```json
{
  "target_type": "world_colony",
  "target_world_key": "field:mining:1820:2470",
  "target_world_x": 1820,
  "target_world_y": 2470,
  "planet_role": "mining",
  "target_name_key": "strategic_world_name_…",
  "target_name": null,
  "legacy_coords": { "galaxy": 1, "system": 302, "position": 7 }
}
```

## Follow-ups

- ~~**GC-590B** — Fleet UI: named target panel, hide G:S:P inputs~~ (done)
- **GC-591** — Role-based colony sidebar
- **GC-592** — Right panel → command center
