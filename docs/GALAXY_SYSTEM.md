# Galaxy System

Koordinaten, Systemansicht und Kolonisierungs-Slots (v1.5.3).

Kanonisches Modul: `game/galaxy.py`.

---

## Koordinatenmodell

Format: `[G:S:P]` — Galaxy : System : Position

| Dimension | Bereich |
|-----------|---------|
| Galaxy | 1 … `game_settings.galaxy_count` (clamp 1–20) |
| System | 1 … 499 |
| Position | 1 … 15 (belegbare Planeten-Slots) |
| Position 16 | **Expedition slot** (synthetisch, kein DB-Planet) |

Parser/Formatter: `parse_coordinates()`, `format_coordinates()` in `galaxy.py`.

---

## Schema

Migration `016`: `planets.galaxy`, `system`, `position`

Migration `026`: Unique index `idx_planets_galaxy_system_position` (partial, where coords not null)

- `assign_free_coordinates()` — neue Kolonie / Homeworld repair
- `repair_missing_coordinates()` — Admin/maintenance
- Occupancy checks vor Kolonisierung

---

## Systemansicht

`list_system(galaxy, system, viewer_player_id, active_planet_id)`:

- 15 Slots mit Metadata: class, temp, score, owner, ally/own flags
- `is_active_planet` wenn Slot = active colony
- Expedition slot via `build_expedition_slot()` (Position 16)

Session-Navigation: `galaxy_view_galaxy`, `galaxy_view_system` in Flask session für SSR.

Default coords wenn URL leer: **active/context planet** coordinates.

---

## Routes

| Route | Methode | Rolle |
|-------|---------|-------|
| `/galaxy` | GET | SSR — Minimap, prev/next, 15 slots + expedition row |
| `/api/galaxy/system` | GET | JSON — `?galaxy=&system=` |

Partial: `templates/partials/galaxy_fleet_actions.html` — Mission-Links zu `/fleet?target_*&mission=`.

Leere Slots: colonize target + `data-galaxy-colony-target`.

---

## Fleet-Integration

Galaxy → Fleet via Query-Params:

```
/fleet?target_galaxy=1&target_system=42&target_position=7&mission=spy
```

Client: `applyFleetUrlPrefill()` in `static/main.js`.

Fleet target resolution: `resolve_fleet_target()` in `fleet.py` — own / ally / foreign / empty / expedition.

Kolonisierung: leerer Slot + `mission=colonize` + `seed_ark` in Flotte.

Details: [FLEET_SYSTEM.md](FLEET_SYSTEM.md).

---

## Frontend

- Module: `GC.modules.galaxy` → `initGalaxy()`
- **Kein Live-Slot-Refresh** — SSR + PJAX navigation
- `prefetchGalaxyAdjacent()` — `<link rel=prefetch>` für prev/next/minimap
- `/api/galaxy/system` wird aktuell **nicht** vom Client für Live-Updates genutzt

Navigation: GET `/galaxy?galaxy=N&system=M` (PJAX shell swap).

---

## Radar / Scan (Prepared)

`radar_array` Gebäude + `EffectResolver` → `scan_range` modifier.

**Kein Scan-Engine** — Modifier nur in Admin debug / prepared state.

Siehe [EFFECTS.md](EFFECTS.md).

---

## Planet Scope

- `active_planet_id` markiert aktiven Slot in Systemansicht
- Alle Kolonien des Spielers erscheinen in Fleet quick-target chips (nicht nur active)

Siehe [PLANET_SCOPE.md](PLANET_SCOPE.md).

---

## Tests

```bash
python -m pytest tests/test_galaxy.py tests/test_planet_visuals.py -v
```
