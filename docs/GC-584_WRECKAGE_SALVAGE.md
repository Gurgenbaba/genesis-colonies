# GC-584 — Wreckage / Salvage Fields

**Status:** ✅ Phase 1  
**Owner:** `game/planet_evolution/world_colonization.py`, `game/fleet.py`, `game/expedition_events.py`

## Ziel

`wreckage_field` wird vom „Prepared“-Hinweis zu einem spielbaren Map-Ziel:

```text
Wrackfeld → Bergung starten → Fleet (mission=expedition + world_key) → Bericht
```

## Scope Phase 1

| In | Out |
|----|-----|
| `SALVAGE_WORLD_TYPES` (`wreckage_field`) | Recycler / `recycle`-Mission |
| `validate_world_salvage_target` + Preview API | Neue Loot-Tabellen |
| Inspector: Bergung vorbereiten / starten | Combat |
| Fleet nutzt kanonische `expedition`-Pipeline | Classic Slot-16-Änderung |
| Report `report_kind: world_salvage` + Weltname | Migration |

## APIs

- `GET /api/worlds/salvage-preview?world_key=…` — `can_salvage`, `can_start_salvage`, `has_salvage_ships`

## Fleet

- Send: `mission=expedition` + `world_key` (wie GC-583A)
- `_expedition_fleet_target` akzeptiert Expedition- **und** Salvage-Worlds
- Outcome: bestehende Expedition-Events, bei `wreckage_field` nur salvage-taugliche Keys (`debris_salvage`, `mineral_deposit`, `fuel_cache`, `distress_beacon`)

## UI

- Map-Badge: „Bergung aktiv“ / Rückkehr / Bergungsbericht
- Inspector: Salvage-Aktionen, Activity wie GC-583C (gleiche `fleet_movements`)
- Fleet-Prefill: `/fleet?mission=expedition&world_key=…`

## Tests

- `tests/test_gc584_wreckage_salvage.py`
