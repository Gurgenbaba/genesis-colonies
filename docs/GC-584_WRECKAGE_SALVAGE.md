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

---

## Player Article

```yaml
---
codex_id: salvage
band: III
difficulty: intermediate
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - empire_view
  - fleet_view
  - galaxy_view
related_codex:
  - expeditions
  - fleet
  - asteroids
  - combat
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: empire_view
teaser_key: codex_unlock_salvage_teaser
---
```

## Quick Help

**Bergung (Salvage)** erschließt **Wrackfelder** auf der Command Map: Expeditions-Mission zur Welt, Bergungsbericht statt klassischem Slot-16-Expo-Ersatz.

## Summary

`wreckage_field`-Welten sind spielbare Map-Ziele. Im Inspector startest du die Bergung; die Flotte fliegt mit Mission **Expedition** und `world_key`. Outcomes nutzen salvage-taugliche Event-Keys (Debris-Funde, Mineral-Caches, Distress). Parallel bleibt die klassische **Recycle**-Mission für Combat-Debris und Asteroiden — anderer Zieltyp, gleiche Ernter-Schiffe möglich.

## Why

Wracks erzählen Verlust und Opportunity auf der Imperiumskarte, ohne Combat auf der Salvage-Welt zu erzwingen. Bergung erweitert die Expeditions-Pipeline statt einer zweiten Fleet-Engine.

## How it works

- Command Map / Empire: Wrackfeld mit Badge „Bergung“ finden.
- Preview prüft Schiffe und Startbarkeit; Inspector → Bergung vorbereiten/starten.
- Fleet-Prefill: Expedition + World-Key; Activity wie bei anderen World-Missionen.
- Rückkehr: Bergungsbericht (`world_salvage`) mit Weltname.
- Debris nach PvP: separate Recycle-Mission auf Galaxy-Slots — nicht mit Wrackfeld verwechseln.

## Related Systems

- expeditions
- fleet
- asteroids
- combat
- galaxy

## Commander Tips

- Salvage-Schiffe vor dem Start prüfen — Preview spart Fehlflüge.
- Wrackfeld ≠ Asteroid ≠ Debris: Mission und Zieltyp in der UI lesen.
- Berichte im Posteingang behalten Kontext für Folgeflüge.

## FAQ

**Ist Bergung ein Kampf?**
Phase-1-Wrackfelder nutzen die Expeditions-Outcome-Pipeline ohne Combat-Focus auf der Salvage-Welt.

**Welcher Unterschied zu Asteroiden?**
Asteroiden: klassische Slots, Recycle, First-Arrival. Salvage: Command-Map-Welt, Expedition + world_key.

**Brauche ich einen eigenen Recycler-Bau?**
Nein — kanonische Fleet-Missionen und vorhandene Ernter/Expeditions-Schiffe.

## Discord Summary

**Bergung — Wrackfelder auf der Map**

Command Map → Expedition mit World-Key → Bergungsbericht. Debris/Asteroiden bleiben Recycle. Keine zweite Fleet-Engine.
