# Galaxy System

Koordinaten, Systemansicht und Kolonisierungs-Slots (Stand v1.5.9.2).

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

Default coords wenn URL ohne `galaxy`/`system`/`q`: immer **active/context planet** (auch nach Galaxie-Browsing oder Planetenwechsel).

Client: `localStorage` key `gc_galaxy_prefs_v2` merkt nur `system` als View — keine Wiederherstellung der Weltkarte (GC-593B). Sidebar-Galaxie-Link setzt `view=system`, Koordinaten kommen vom Server. Bei Planetenwechsel synchronisiert `/api/planets/active` die Session-Coords mit dem neuen Planeten.

Priorität: URL > active planet coords.

---

## Routes (GC-593 — klassische Galaxie ist Hauptansicht)

| Route | Methode | Rolle |
|-------|---------|-------|
| `/galaxy` | GET | SSR — **Default:** klassische Systemansicht (`view=system`) |
| `/galaxy?view=system` | GET | **Hauptansicht** — 15 belegbare Slots + Expeditions-Slot (Pos 16) |
| `/galaxy?view=command_map` | GET | **DEV/Legacy Preview** — nur mit `?dev=1` oder `GC_COMMAND_MAP_DEV_MODE=1` |
| `/api/galaxy/system` | GET | JSON — `?galaxy=&system=` |

**Zwei Ansichten, eine Route.** Tabs in `templates/galaxy.html` (Weltkarte-Tab nur im Dev-Preview). Koordinatenmodell `[G:S:P]` bleibt kanonisch für Fleet, Kolonisierung und Systemansicht.

Die **Weltkarte** ist aus dem Spieler-Hauptflow entfernt (GC-593); Code bleibt für Dev-Preview und Backend-Contracts. Historische Spec: [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md).

Vision: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · GC-560: [GC-560_EMPIRE_IDENTITY_LAYER.md](GC-560_EMPIRE_IDENTITY_LAYER.md)

**`/empire` ist keine Command Map** — Wirtschafts-/Produktionsmatrix; nicht mit Imperiumsidentität vermischen.

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
- `prefetchGalaxyAdjacent()` — lädt prev/next per **PJAX-Memory-Cache** + `warmGalaxyRingImages()` (Idle-Prefetch)
- Planet-/Map-/Debris-Assets mit `?v={{ GC_ASSET_VERSION }}` → Browser **immutable** 1y Cache
- `/api/galaxy/system` wird aktuell **nicht** vom Client für Live-Updates genutzt

Navigation: GET `/galaxy?galaxy=N&system=M` (PJAX shell swap).

---

## Radar / Scan (Deep-Space Threat Net)

`radar_array` → EffectResolver `scan_range` (`2 × level`, plus Envoy class bonus).

**Passive Threat Net** ([`game/fleet.py`](../game/fleet.py) `build_radar_contacts`):

- Each colony with radar projects a bubble of `scan_range` **system steps** (same galaxy; cross-galaxy when range ≥ 8).
- Detects foreign `outbound` missions `attack` / `spy` / `deploy` whose origin **or** target lies in a bubble.
- Progressive intel tiers (ETA band → coords → owner → fuzzy roles → full ships).
- Live payload: `fleet_alerts.radar_contacts` via `/api/game-state` (no module poll).

Spy probes remain a separate grounded-intel channel.

Siehe [EFFECTS.md](EFFECTS.md), [FLEET_SYSTEM.md](FLEET_SYSTEM.md).

---

## Planet relocation (Evakuierung)

Owner: `game/galaxy.py` · Migration `093_planet_relocation`

Spieler können den **aktiven Planeten** im Kolonie-Dialog (Overview → Planetenname) an eine **freie Position** `[G:S:P]` (1–15) verlegen.

| Regel | Wert |
|-------|------|
| Dauer | 1 h (`RELOCATION_DURATION_SECONDS`) — Evakuierung, Planet bleibt bis Abschluss an alter Position |
| Cooldown | 24 h pro Planet (`RELOCATION_COOLDOWN_SECONDS`) |
| Ziel | Nur unbelegte Slots; bei Belegung zum Finish-Zeitpunkt → Status `failed` |
| Finish | `finish_due_relocations()` via `queue_engine.finish_due_work` |

API: `POST /api/planet/relocation/start` `{ galaxy, system, position }` → `{ ok, state }`.

**Galaxie-UX:** Leerer Slot im Ring-Inspektor:
- `seed_ark` irgendwo im Imperium → **Kolonisieren** (Fleet-Link)
- kein `seed_ark`, aktiver Planet darf umziehen → **Umzug**-Button (`data-galaxy-relocation-start`)
- Evakuierung aktiv / Cooldown → Hinweis statt Button

Live-State: `planet_relocation` + `has_seed_ark` in `/api/game-state`.

---

## Debris Fields (Trümmer)

Owner: `game/combat.py` (`debris_fields`)

| Rule | Value |
|------|-------|
| Create | Combat losses → `spawn_combat_debris_*` / `add_debris_field` |
| Harvest | Mission `recycle` arrival → `harvest_debris_at_field` (DELETE when M/C ≤ 0) |
| TTL | `DEBRIS_FIELD_TTL_SECONDS` (7d from `updated_at`) — **hard expire** via `expire_due_debris_fields` |
| Cron | Fleet-worker piggyback + defensive purge in `get_debris_for_system` / `get_debris_at_field` |
| Galaxy | Slot `has_debris` / `debris` only while amount > 0 and TTL remaining |
| Live sync | On Galaxy page: recycle outbound→returning (via `active_fleets` delta) triggers soft `reloadCurrentPage({ force: true })` with `invalidateGalaxyPjaxCache` + HTTP `no-store` — no module-owned poll (GC-DEBRIS-LIVE-01 / GC-GAL-TFS-01). Send-success does **not** reload (would cache pre-harvest SSR). |

---

## Asteroid Belt (GC-AST)

Owner: `game/asteroids.py` — [ASTEROID_SYSTEM.md](ASTEROID_SYSTEM.md)

Temporary fields on free classic slots in dense systems (TTL 2 h). Slot flags: `has_asteroid` / `asteroid`. Harvest via Fleet mission `recycle` + `harvest_reclaimer` (first arrival claims). Galaxy board lists active fields with jump links; own outbound hunts show en-route ETA (durable `asteroid_engagements`). Same-slot respawn blocked until field `expires_at`. Details: [ASTEROID_SYSTEM.md](ASTEROID_SYSTEM.md).

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

---

## Player Article

```yaml
---
codex_id: galaxy
band: II
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
routes:
  - galaxy_view
  - empire_view
related_codex:
  - expansion
  - fleet
  - planet_evolution
  - genesis_ark
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

Die **Galaxie** zeigt dein Reich im Raum: **Weltkarte** (Command Map) mit Imperium, Orten und Expansion — plus klassische **Systemansicht** für Slots und Flotten-Prefill.

## Summary

Koordinaten `[G:S:P]` bleiben intern; Spieler sehen benannte **Orte**, **Regionen** und **Einfluss**. Route `/galaxy` bietet zwei Tabs: **Weltkarte** (`view=command_map`) als strategische Hauptansicht und **klassische Systemansicht** (`view=system`) mit 15 belegbaren Slots plus Expeditions-Slot.

## Why

Galaxie ist nicht nur Koordinatenbrowser — sie verbindet **Entdeckung, Expansion und Flotten**. Die Weltkarte macht Imperiumswachstum sichtbar; die Systemansicht bleibt Legacy-Fallback und Fleet-Brücke.

## How it works

- **Weltkarte:** Genesis Ark als Hub, Kolonien mit Rollen, Expansion Sites, Strategic Worlds, Chokepoints, Einflussgebiet — Aktionen abhängig von Entwicklungsstufe und Gates.
- **Systemansicht:** 15 Planetenpositionen pro System; leere Slots → Kolonisierung per Flotte; Position 16 = Expeditions-Slot (synthetisch).
- Navigation merkt den letzten Tab; Koordinaten folgen oft dem **aktiven Planeten**.
- Flotten-Prefill von Galaxie: Mission-Links mit Zielkoordinaten oder `world_key`.
- **`/empire`** ist **keine** Command Map — Wirtschafts-/Produktionsmatrix (nicht mit Weltkarte verwechseln).

## Related Systems

- expansion
- fleet
- planet_evolution
- planet_scope

## Commander Tips

- Expansion planen auf der **Weltkarte**, nicht nur in der Slot-Liste.
- Aktiver Planet markiert den Slot in der Systemansicht.
- Expeditions-Slot ist kein normaler Kolonie-Planet.

## FAQ

**Weltkarte vs. Systemansicht?**
Weltkarte = Imperium und Orte. Systemansicht = klassische Slot-Karte — beide unter `/galaxy`.

**Wo ist die Command Map?**
Default-Tab **Weltkarte** auf `/galaxy` — nicht auf `/empire`.

## Discord Summary

**Galaxie — Weltkarte und Systemansicht**

`/galaxy`: Weltkarte (Command Map, Imperium, Expansion) + klassische Systemansicht (Slots, Expedition). Koordinaten intern. `/empire` = Wirtschaft, nicht Karte.
