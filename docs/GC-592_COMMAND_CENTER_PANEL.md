# GC-592 — Command Center Panel v2

> Die Weltkarte wird zur zentralen Steuerfläche. Das rechte Panel wechselt je nach Kartenauswahl zwischen Imperiums-Command-Center, Strategic-World-Inspector, Fremdkolonie und Expeditionszone.

## Vision

```
Weltkarte → Auswahl → Command Center (rechts) → Gebäude / Flotte / … → zurück zur Karte
```

Langfristig ersetzt `/overview` + Sidebar-Navigation durch: Header · Karte · Rollen-Sidebar · Command Center · Event-Leiste.

## Sub-Tickets

| Ticket | Scope | Status |
|--------|--------|--------|
| **GC-592A** | Eigene Kolonie: Ressourcen, Flotten, Schnellaktionen, Neuigkeiten, „Kolonie öffnen“ | **Done** |
| **GC-592B** | Strategic World: Risiko, Bekanntheit (GC-583D), Versprechen, Kolonisieren / Expedition / Bergung | **Done** |
| **GC-592C** | Fremde Kolonie / Fremdes Reich: public-only Intel, Spionieren / Angreifen / Beobachten (disabled) | **Done** |
| **GC-592D** | Expedition / Anomalie / Ruinen / Wrackfeld — spezialisiertes Command Center | **Done** |
| GC-592E | Ein Panel-Container; Site-Inspector nur Landmarks/Expansion | Backlog |

## Owner (GC-000)

| Domäne | Modul |
|--------|--------|
| Server-Payload (Ressourcen, Flotten, News, Quick-Grid) | `game/planet_evolution/command_center.py` |
| Einbindung in Map-Payload | `game/planet_evolution/command_map.py` → `attach_command_centers_to_nodes()` |
| UI-Shell | `templates/partials/galaxy_command_map_panel.html` |
| Client-Rendering | `static/main.js` → `renderCommandCenterPanel()` |

## GC-592A — Own Colony Payload

`build_colony_command_center(planet_id, player_id, …)` liefert:

- `resources`: Fe / Cr / Fuel + stündliche Raten (Server: `update_planet_resources` + `EffectResolver`)
- `fleets`: bis zu 4 aktive Bewegungen am Planeten; Fallback „Verteidigung bereit“
- `quick_actions`: 2×3-Grid aus `location_actions` (Gebäude, Flotte, Werft, Evolution, Handel, Logistik)
- `news`: letzte Posteingang-Betreffzeilen
- `status_key`: optional `command_map_badge_newly_colonized`

JSON pro Kolonie: `data-command-center` auf `[data-colony-actions-source]`.

## GC-592B — Strategic World Payload

`build_strategic_world_command_center(node, player_id, …)` liefert `panel_kind: strategic_world`:

- `details`: Risiko, Versprechen, Bonus, Zukunftsaktion (locale keys)
- `familiarity`: GC-583D-Fortschritt für Expeditionswelten
- `expedition_activity`: GC-583C-Status (aktiv / Rückkehr / Bericht)
- `primary_action`: `colonize` | `expedition` | `salvage` | `none` (+ `world_key`, `enabled`, `blocked_reason_key`)
- `hints`: Kolonie-Limit, Nicht-kolonisierbar, Bergungs-Hinweise

Attach nach `apply_shared_world_layout` (Expedition + Progress bereits am Node). JSON: `data-world-field-source` + `data-command-center`.

Klick auf Strategic World → `GC.showCommandMapStrategicWorldPanel()` (Site-Inspector bleibt im DOM, wird nicht primär genutzt).

## GC-592C — Foreign Colony Payload

`build_foreign_colony_command_center(node, viewer_player_id, …)` liefert `panel_kind: foreign_colony` (nur public):

- `details`: Besitzer, Koordinate, Rolle, Allianz (wenn öffentlich), Stärke (Ranking-Score), Kolonieanzahl (Reich)
- `actions`: Spionieren / Angreifen → Fleet mit `target_type=enemy_colony` + `world_key`; Beobachten disabled
- Keine Ressourcen, Flotten, Defense, Schiffe, News

Nodes: `foreign_world_colony`, `foreign_empire` (+ optional `foreign_colony`). JSON: `data-foreign-colony-source`.

## GC-592D — Expedition Site Payload

`build_expedition_site_command_center(node, …)` für `expedition_zone`, `anomaly_zone`, `ruins_world`, `wreckage_field`:

- `panel_kind: expedition_site`, `site_kind`, Typ-Status im Header, `risk_key` unter dem Titel
- `details`: Versprechen, Risiko, Fund-Hint, Zukunftsaktion
- `familiarity` + `expedition_activity` (583D / 583C), Expedition Count im UI
- `primary_action`: Expedition oder Bergung; `hints` inkl. Salvage-Prepare

Kolonisable `world_field`-Nodes bleiben `panel_kind: strategic_world`.

## Nicht in Scope (592A–D)

- Frontend-Berechnung von Produktion oder Flugzeiten
- Ersetzen des Site-Inspectors
- `/overview`-Layout-Umbau

## Tests

- `tests/test_gc592_command_center.py`
- Regression: `tests/test_command_map.py`, `tests/test_gc582d_world_map_colonies.py`
