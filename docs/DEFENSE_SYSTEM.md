# Defense System

Planet-scoped defensive structures — build queue, stock persistence, ranking, spy intel, and **active combat** integration (v1.5.4).

Kanonische Module: `game/defense.py`, `game/defense_defs.py`, `game/defense_api.py`, `game/defense_page.py`, `game/models.py` (planet_defense CRUD).

Defense stock is resolved in `attack` missions via `simulate_battle()` — see [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md).

---

## Übersicht

Das Defense-System verwaltet **stationäre Abwehreinheiten pro Kolonie**:

- Bau über `defense_factory` und planet-scoped `defense_queue`
- Bestand in `planet_defense`
- Live-UI unter `/defense` (Parität mit Orbitalwerft)
- Empire-weiter **Defense Score** für Ranking und PlayerCard
- Spy-Berichte ab Stufe 5 (≥5 `veil_probe`)

### Abgrenzung

| Domäne | Defense | Andere Systeme |
|--------|---------|----------------|
| **Fleet** | Stationär am Planeten, kein Flug | Bewegliche Schiffe, Missionen, Tick — [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| **Buildings** | `defense_factory` schaltet Einheiten frei | Allgemeine Gebäude-Queue — [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| **Combat** | Werte in `defense_defs` / `combat_models`; losses via `game/combat.py` | Applied on attack arrival ([COMBAT_SYSTEM.md](COMBAT_SYSTEM.md)) |
| **Planet Evolution** | Unabhängig | DNA, Policies, Planet-Tech — [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| **Research** | Unlock-Requirements (`weapon_tech`, `shield_tech`, …) | Account-weite Levels — [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |

---

## Planet Scope

Defense folgt [PLANET_SCOPE.md](PLANET_SCOPE.md) — analog zu `planet_ships`.

| Daten | Scope | Zugriff |
|-------|-------|---------|
| Bestand (`planet_defense`) | **Planet** | `get_planet_defense(planet_id)` |
| Bau-Queue (`defense_queue`) | **Planet** | `list_defense_queue_rows(planet_id)` |
| Planet-Ressourcen für Kosten | **Planet** | `planets.metal/crystal` des aktiven Planeten |
| Research-Requirements | **Account** | `get_research_levels(user_id)` |
| Gebäude-Requirements | **Planet** | `get_planet_buildings(planet_id)` |
| Defense Score (Ranking) | **Empire** | Summe über alle Kolonien des Spielers |
| Spy-Snapshot | **Ziel-Planet** | `get_planet_defense_intel(planet_id)` |

### Kontext-Planet

| Operation | Auflösung |
|-----------|-----------|
| SSR `/defense` | `get_context_planet(user_id)` |
| `GET /api/defense*` | `?planet_id=` oder aktiver Kontext |
| `POST /api/defense/build`, `/cancel` | `planet_id` im Body oder Kontext |
| Planetwechsel | Client setzt `data-planet-id`; Poll nutzt neuen Kontext |

Backend: `defense_api.resolve_context_planet_id()` → `shipyard.resolve_owned_planet_id()` (Besitz + Session-Kontext).

Gate ohne Migration: `defense_schema_ready()` + `defense_queue_table_ready()` — APIs antworten `defense_unavailable` (503), UI zeigt leeren Zustand.

---

## Schema

| Tabelle | Migration | Rolle |
|---------|-----------|-------|
| `planet_defense` | `039_defense_foundations.sql` | `(planet_id, defense_key, amount)` — fertiger Bestand |
| `defense_queue` | `040_defense_queue.sql` | Bauaufträge pro Planet |

### `planet_defense`

- `UNIQUE(planet_id, defense_key)`
- Nur Zeilen mit `amount > 0` in Client/API-Maps (via `get_planet_defense`)
- CRUD: `get_planet_defense`, `set_planet_defense`, `add_planet_defense` in `game/models.py`
- Empire-Aggregat: `get_player_defense_counts(player_id)` für Ranking

### `defense_queue`

- Felder: `player_id`, `planet_id`, `defense_key`, `amount`, `status`, `started_at`, `finish_at`, `queue_position`, `cost_metal`, `cost_crystal`
- Status: `queued` (aktiv in Queue-Engine), `completed`, `cancelled`
- Kosten werden beim Einreihen gespeichert (für GC-831 Refund bei Cancel)

Ranking-Spalte `player_scores.score_defense` existiert seit Migration `014_ranking_hardening.sql`.

---

## Defense Units

Definiert in `game/defense_defs.py` — Reihenfolge `DEFENSE_ORDER` / `ACTIVE_DEFENSE_KEYS` (7 Einheiten).

| Key | Rolle | Fabrik-Stufe | Gebäude / Forschung (Auszug) |
|-----|-------|--------------|------------------------------|
| `slug_launcher` | turret | 1 | `defense_factory` 1 — günstige Massen-Geschossbatterie (Raketenwerfer-Rolle; ferronitlastige Kosten) |
| `sentinel_turret` | turret | 1 | `defense_factory` 1, `weapon_tech` 2 |
| `plasma_arc` | turret | 2 | `defense_factory` 2, `weapon_tech` 4 |
| `ion_bastion` | turret | 4 | `defense_factory` 4, `weapon_tech` 6, `armor_tech` 3 |
| `flak_array` | turret | 5 | `defense_factory` 5, `radar_array` 1, `weapon_tech` 8, `armor_tech` 4 |
| `pulse_barrier` | shield | 6 | `defense_factory` 6, `shield_generator` 1, `shield_tech` 6, `armor_tech` 3 |
| `orbital_shield` | shield | 8 | `defense_factory` 8, `shield_generator` 3, `shield_tech` 8, `energy_tech` 5 |

Jede Definition enthält:

- `name_key` / `description_key` / `role` (i18n + UI-Badge)
- `build_cost`: `{ metal, crystal }` — Quelle für Kosten und Fallback-Score
- `build_seconds` — Basis-Bauzeit (skaliert mit Fabrik-Stufe)
- `requirements`: `{ buildings, research }` — geprüft via `defense_unlocked()`
- **Combat prep:** `attack`, `shield`, `hull`, `score_value`, `rapid_fire_targets`

Bau-Gebäude: `defense_factory` — siehe [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md).

Icons: `/static/img/defense/<key>.png`

Detail-Modal: `GET /api/defense-units/<defense_key>` → `game/defense_detail.py` + `defense_requirements.py`.

---

## Build Queue

Implementierung: `game/defense.py` (Queue-Logik), Auslieferung über [Queue Engine](#queue-engine-integration).

| Regel | Wert |
|-------|------|
| Max. Aufträge | 3 (Default `MAX_DEFENSE_QUEUE`; Override `defense_queue_limit` / Fallback `shipyard_queue_limit` in Game Settings) |
| Kosten | Sofort beim Einreihen von Planet-Ressourcen abgebucht |
| Lieferung | **Progressiv** — Einheiten erscheinen nacheinander im Bestand (`progressive_units_to_deliver`) |
| Bauzeit | `build_seconds` × Fabrik-Level-Faktor (`BUILD_TIME_LEVEL_FACTOR` 0.90) × globale `shipyard_speed` |
| Cancel | Nur Jobs mit `status = queued`; **GC-831 Refund** (100 % pending / 50 % active) via `queue_refund.refund_from_stored_costs` |

Ablauf `build_defense()`:

1. Validierung (Unlock, Ressourcen, Queue-Limit, `amount > 0`)
2. Ressourcen abbuchen, Queue-Zeile anlegen
3. `recalculate_queue_finish_times()`
4. Nach Lieferung: `add_planet_defense()` + optional `apply_score_updates_for_players()` (Poll-Pfad)

Abbruch: `cancel_defense_job()` in `defense_api.py` — löscht Job, GC-831 Refund, renummeriert Queue.

---

## Queue Engine Integration

`queue_engine.finish_due_work()` ruft `finish_planet_defense_jobs()` auf:

- Liefert fällige Einheiten pro Planet
- Zählt in `result["finished"]["defense"]`
- Triggert `apply_score_updates_for_players()` für betroffene Spieler

Zusätzlich: `defense_queue_for_client()` und Legacy-Poll `GET /api/defense` rufen `finish_due_defense_jobs_for_planet()` vor der Queue-Anzeige auf (gleiche Liefer-Logik).

---

## APIs

### Canonical envelope (GC-413)

Mutations und `GET /api/defense/state` liefern:

```json
{ "ok": true, "state": { ...game-state... }, "queue": { ... }, "defenses": { ... } }
```

Fehler: `{ "ok": false, "error": "...", "state", "queue", "defenses" }` via `_defense_json_response()` in `app.py`.

Idempotenz: `request_id` / Header `X-Request-Id` auf `POST /api/defense/build` und `/cancel`.

### Routen

| Route | Methode | Zweck |
|-------|---------|-------|
| `/defense` | GET | SSR-Seite (`defense.html`, embedded JSON state) |
| `/api/defense` | GET | Legacy Poll — `fleet_ok({ data: page_context })` |
| `/api/defense/state` | GET | Kanonischer Live-State (`queue` + `defenses` slices) |
| `/api/defense/overview` | GET | Wie state + `overview`-Slice (Stock-Summary) |
| `/api/defense/build` | POST | `{ defense_key, amount, planet_id?, request_id? }` |
| `/api/defense/cancel` | POST | `{ job_id, planet_id?, request_id? }` |
| `/api/defense-units/<defense_key>` | GET | HTML-Partial für Detail-Modal (Login) |

Planet-Auflösung: Query/Body `planet_id` oder Session-Kontext-Planet.

---

## Frontend

Template: `templates/defense.html` — Layout wie Orbitalwerft (Fabrik-Stufe → Queue → Bestand → Baubar → Gesperrt).

JavaScript (`static/main.js`):

- Modul: `GC.modules.defense` → `initDefense()`
- Initial state: `#defense-page-state` JSON
- Poll: `GET /api/defense?planet_id=` — `normalizeDefenseApiPayload()` für Build/Cancel-Responses
- Queue: Fortschrittsbalken, Cancel-Button, `DEFENSEQ` Timer + `GC.startProgressTicker()`
- Inventar + Baubare Karten: `data-defense-detail` → gemeinsames Schiff/Defense-Detail-Modal
- **Keine Success-Toasts** bei Bau/Cancel (Queue-UI reicht); Fehler-Toasts bleiben
- PJAX: Cleanup via `GC.registerCleanup(stopDefenseTimers)`; Seite neu initialisiert nach Navigation

Live-State: `GET /api/game-state` kann optional `defense`-Panel enthalten (`defense_panel_for_game_state()` in `game/live_state.py`).

---

## Ranking Integration

| Metrik | Berechnung |
|--------|------------|
| **Defense Score** | `sum(amount × score_value)` über alle Planeten → Exponent `score_cost_exponent` in `compute_player_scores()` |
| **Military Score** | `fleet_score + defense_score` (abgeleitet, **nicht** doppelt in `total_score`) |
| **PlayerCard** | `score_defense` in `read_player_scores_for_playercard()` |
| **Ranking-Tab** | `defense_score` — Tab „Verteidigung“ in `/ranking` |
| **Kategorie-Rang** | `get_player_category_ranks()` → `ranks.defense` |

Module: `game/scoring.py` (`compute_defense_empire_sum`, `compute_military_score`), `game/ranking.py`.

Score-Refresh nach Lieferung: `score_events.apply_score_updates_for_players()` (Queue Engine + Defense-Poll-Pfad).

---

## Intelligence / Spy

**Aktiv** — integriert in GC-401 Spy-Pipeline (`game/spy.py`).

| Aspekt | Verhalten |
|--------|-----------|
| Snapshot | `build_spy_snapshot()` inkl. `get_planet_defense_intel(planet_id)` |
| Tier | **≥5 Probes** (`SPY_INTEL_TIER_DEFENSE`) — gleiche Schwelle wie Gebäude-Tier |
| Sichtbarkeit | Begrenzte Anzahl Einheitentypen (Priorität über `defense_combat_priority`) |
| Genauigkeit | `espionage_tech` via `spy_accuracy()` — gerundete Werte im Bericht |
| Aggregat | `total_units`, `defense_power`, `shield_power` (aus `summarize_defense_stock`) |
| Inbox | `append_spy_defense_report_lines()` in `game/messages.py`; UI `renderSpyReport()` in `static/js/messages.js` |

Eigene Kolonie: Defense-Intel im Spy-Bericht unterdrückt (wie Flotte).

---

## Combat integration

| Modul | Rolle |
|-------|-------|
| `game/combat_models.py` | `CombatUnitStats`, `CombatStack`, `combat_stats_for_defense()`, `stacks_from_counts()` |
| `game/combat.py` | `simulate_battle()`, debris, defender loss helpers |
| `game/defense_defs.py` | Rohdaten + `defense_combat_stats()` |
| `game/fleet.py` | Attack arrival applies `planet_defense` losses |

Felder pro Einheit (Defs + `CombatUnitStats`):

- `attack`, `shield`, `hull`, `score_value`
- `rapid_fire_targets`: Map Ziel-`unit_key` → Faktor (≥2); bonus shot chance in resolver

```python
from game.combat_models import combat_stats_for_defense, stacks_from_counts, COMBAT_UNIT_DEFENSE

stats = combat_stats_for_defense("flak_array")
stacks = stacks_from_counts(planet_stock, unit_type=COMBAT_UNIT_DEFENSE)
```

Full flow: [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md).

---

## Abhängigkeiten

| System | Nutzung |
|--------|---------|
| Buildings | `defense_factory`, `radar_array`, `shield_generator` |
| Research | `weapon_tech`, `shield_tech`, `armor_tech`, `energy_tech`, `espionage_tech` (Spy) |
| Planet Scope | Kontext-Planet, Ressourcen |
| Queue Engine | Zentrale Fertigstellung + Score-Updates |
| Ranking / PlayerCard | `score_defense`, `military_score` |
| Fleet / Spy | Snapshot + Tier-5-Intel |
| Shipyard | Shared Patterns (Queue-UI, `resolve_owned_planet_id`, Speed-Settings) |

---

## Dateien

| Datei | Rolle |
|-------|-------|
| `game/defense.py` | Queue, Build, Cancel, Lieferung, API-Payload |
| `game/defense_defs.py` | Einheiten-Registry, Icons, Combat-Rohdaten |
| `game/defense_api.py` | JSON-Envelope, Slices, Cancel mit Erstattung |
| `game/defense_page.py` | SSR + Page-Context (`build_defense_page_context`) |
| `game/defense_detail.py` | Detail-Modal-Payload |
| `game/defense_requirements.py` | Requirements-Summary für UI |
| `game/scoring.py` | Empire-Summe, Military-Score |
| `game/combat_models.py` | Combat stats / stack builder |
| `game/combat.py` | Battle engine + debris |
| `game/spy.py` | Defense-Intel im Spy-Snapshot |
| `game/models.py` | `planet_defense` CRUD, Schema-Gates |
| `game/live_state.py` | Game-State-Panel, `defense_finish_source` |
| `game/ranking.py` | Defense Score in `compute_player_scores()` |
| `game/queue_engine.py` | `finish_planet_defense_jobs()` |
| `game/score_events.py` | Score-Recompute nach Lieferung |
| `app.py` | Routen `/defense`, `/api/defense*` |
| `templates/defense.html` | SSR-UI |
| `templates/partials/defense_detail_view.html` | Detail-Partial |
| `static/main.js` | `initDefense`, Poll, Build/Cancel |
| `migrations/039_defense_foundations.sql` | `planet_defense` |
| `migrations/040_defense_queue.sql` | `defense_queue` |

---

## Placeholder / Phase 2

| Item | Status |
|------|--------|
| Recycler mission (harvest debris fields) | 📋 Phase 2 |

---

## Tests

```bash
python -m pytest tests/test_defense_detail_modal.py tests/test_ranking.py tests/test_playercard.py tests/test_queue_engine.py tests/test_fleet.py -v -k "defense or spy_report or score_defense"
```

| Bereich | Tests |
|---------|-------|
| Detail-Modal | `tests/test_defense_detail_modal.py` |
| Ranking / Score | `tests/test_ranking.py` (`defense_score`, `_fleet_defense_select`) |
| PlayerCard | `tests/test_playercard.py` (`score_defense`) |
| Queue Engine | `tests/test_queue_engine.py` (`finished.defense`) |
| Spy (Snapshot) | `tests/test_fleet.py` (Tier-Reports; Defense in Snapshot ab Tier 5) |
| DB Read Paths | `tests/test_db_read_paths.py` (Score-Feld-Mapping) |

---

## Verwandte Dokumente

- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Flotten, Schiffe, Spy-Mission
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — Koordinaten
- [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) — `defense_factory`
- [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) — Unlock-Requirements
- [PLANET_SCOPE.md](PLANET_SCOPE.md) — Aktiver Planet
- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) — Battle engine, debris
- [EFFECTS.md](EFFECTS.md) — Tech-Effekte (combat modifiers active)
- [ROADMAP.md](ROADMAP.md) — Phase 4 / EPIC-08
- [ARCHITECTURE.md](ARCHITECTURE.md) — Modul-Übersicht

---

## Player Article

```yaml
---
codex_id: defense
band: III
difficulty: intermediate
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
routes:
  - defense_view
related_codex:
  - combat
  - fleet
  - buildings
  - research
terminology: GENESIS_TERMINOLOGY
unlock:
  type: building
  building: defense_factory
teaser_key: codex_unlock_defense_teaser
---
```

## Quick Help

Planetare **Verteidigung** schützt die aktive Welt: stationäre Geschütze und Barrieren aus der Verteidigungsfabrik — nicht Flotten im Orbit.

## Summary

Defense verwaltet **stationäre Einheiten pro Kolonie**: Bau über die Verteidigungsfabrik und Defense-Queue, Bestand am Planeten. Live-UI unter `/defense`. Bei **Angriff** kämpfen Hangar-Schiffe und stationäre Verteidigung gemeinsam. Empire-weiter **Defense Score** fürs Ranking.

## Why

Flotten allein reichen nicht — Kolonien brauchen lokale Abwehr. Defense trennt **stationär** (Planet) von **mobil** (Fleet) und speist direkt in Combat und Spy-Intel (ab höherer Spionage-Stufe).

## How it works

- Baue **Verteidigungsfabrik** auf der zu schützenden Welt.
- Öffne **Defense** — Einheiten bauen (Queue wie Werft), Requirements aus Gebäuden und Account-Forschung.
- Einheiten: Türme und Barrieren (z. B. Slug-Werfer, Sentinel, Plasma, Flak, Orbital Shield) — Freischaltung über Fabrik-Stufe und Techs.
- Bestand ist **planetengebunden** — wie `planet_ships`.
- Planetwechsel im Header wechselt die Defense-Ansicht.
- Kampfwerte in Defense-Detail / Technische Daten — nicht Codex.

## Related Systems

- combat
- fleet
- buildings
- research
- planet_scope

## Commander Tips

- Outposts und Mining-Kolonien nicht ohne Defense im PvP-Raum lassen.
- `shield_tech` und `weapon_tech` stärken auch Verteidigung in Combat.
- Defense-Queue parallel zur Werft auf derselben Welt planen.

## FAQ

**Defense vs. Flotte am Planeten?**
Defense = stationär am Planeten. Hangar-Schiffe sind mobil und fliegen mit — beide kämpfen bei Angriff.

**Warum kann ich nichts bauen?**
Fehlende Fabrik-Stufe, Research oder Ressourcen auf der aktiven Welt.

## Discord Summary

**Verteidigung — stationär pro Welt**

Verteidigungsfabrik + Queue + Bestand pro Kolonie. Kämpft bei Angriff mit Hangar. Defense Score im Ranking. Planet Scope beachten.
