# Planet Evolution System

Per-Planet Progression: DNA, Traits, Planet-Forschung, Specialization, Policies, Events (Stand v1.5.9.2).

**Abgrenzung:**

| System | Scope | Doc |
|--------|-------|-----|
| Account-Forschung (`research_levels`) | Spielerweit | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |
| Planet Evolution | Pro Kolonie | dieses Dokument |
| Planet Scope / Switcher | UI-Kontext | [PLANET_SCOPE.md](PLANET_SCOPE.md) |

Modul: `game/planet_evolution/` — Schema ab Migration `016`–`018`.

---

## Kernkonzepte

| Konzept | Beschreibung |
|---------|--------------|
| **Planet DNA** | Traits, Affinities, Rarity, Risk — generiert bei Bootstrap |
| **Planet Level / XP** | Progression pro Kolonie |
| **Planet Class** | Aus DNA + Koordinaten (`dna.effective_planet_class`) |
| **Mechanics** | Kompiliert aus DNA + Research + Policies + Discoveries |
| **Specialization** | Pfad ab Level 8, Tiers, Import/Export |
| **Culture** | Archetype, Stability, Loyalty — Drift im Tick |
| **Events** | Narrative Choices mit Auswirkungen |
| **Ascension** | Langzeit-Fortschritt (Queue) |

---

## Schema

### `planets` (Erweiterung, Migration 016)

Koordinaten, `planet_class`, `planet_level`, `planet_xp`, `specialization_key/tier`, DNA-Felder, `failure_state`, Tick-Timestamps, …

### Per-Planet Tabellen

| Tabelle | Rolle |
|---------|-------|
| `planet_dna` | Traits, Affinities, Potenzial |
| `planet_mechanics` | Kompilierte Unlocks, Flags, Queue-Limits |
| `planet_research_levels` / `planet_research_queue` | **Planet-Tech** (≠ Account-Tech) |
| `planet_locked_choices` | Verzweigte Forschungs-Entscheidungen |
| `planet_policies` | Aktive Policy-Slots + Cooldowns |
| `planet_culture` | Archetype, Drift-Stats |
| `planet_special_resources` | Spezial-Rohstoffe |
| `planet_production_chains` / `planet_conversion_queue` | Ketten-Produktion |
| `planet_trade_routes` | Inter-Kolonie-Transfer |
| `planet_import_demands` | Specialization-Importe |
| `planet_events` | Aktive/pending Events |
| `planet_discoveries` | Entdeckungen |
| `planet_failure_states` | Failure/Recovery |
| `planet_history` / `planet_legacy_tags` | Audit |
| `planet_ascension_queue` | Ascension-Fortschritt |

### Definitionstabellen (`pe_*`, Seed Migration 017)

`pe_trait_definitions`, `pe_research_definitions`, `pe_specialization_definitions`, `pe_policy_definitions`, `pe_event_definitions`, `pe_discovery_definitions`, `pe_special_resource_definitions`, `pe_production_chain_definitions`, `pe_ascension_definitions`

Geladen via `game/planet_evolution/definitions.py` (In-Memory-Cache).

---

## Module

| Datei | Rolle |
|-------|-------|
| `repository.py` | DB-Zugriff, **`get_context_planet()`**, `get_active_planet_id()` |
| `service.py` | Public API: State, Colonize, Policies, Events, Switcher-Rows |
| `bootstrap.py` | `ensure_planet_evolution()` — DNA, Culture, Mechanics für neue/existierende Planeten |
| `dna.py` | Trait-Generierung, Planet Class |
| `mechanics.py` | `compile_planet_mechanics()` |
| `tick.py` | `evolution_tick_planet()` — Culture, Chains, Trade, Events |
| `planet_research.py` | Queue/Status Planet-Tech |
| `specialization.py` | Pick/Upgrade Specialization |
| `events.py` | Event-Engine |
| `ascension.py`, `culture.py`, `discoveries.py`, `economy.py`, `failures.py` | Subsysteme |
| `dashboard.py`, `teaser.py`, `ux_copy.py` | UI-Payloads |
| `planet_level.py`, `scoring.py`, `history.py` | Level/XP, Score, Historie |

---

## Tick-Integration

```
update_planet_resources(planet_row)
  → evolution_tick_planet(planet_id)   # wenn evolution_schema_ready()
```

Läuft für die **jeweilige Planet-Row** (nicht nur active). Queue-Finish: Planet Research + Ascension in `queue_engine`.

### Queue-UX (GC-536E)

Planet-Tech- und Ascension-Queues werden **in den jeweiligen Cards** angezeigt (nicht mehr als großes Seiten-Panel):

| Queue | Owner | Card-Marker | Kompaktstatus |
|-------|-------|-------------|---------------|
| Planet-Tech | `planet_research` / `tech_key` | `data-planet-tech-card`, `data-tech-key` | `#pe-planet-tech-queue-compact` |
| Ascension | `ascension` / `ascension_key` | `data-ascension-card`, `data-ascension-key` | `#pe-ascension-queue-compact` |

Payload: optional `queue_job` pro Card via `game/queue_card.py` (Presentation only). Live-Updates: `/api/planets/<id>/state` → `applyPlanetEvolutionState` + Card-Ticker — siehe [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md).

---

## Planet-Tech — Kosten & Zeit (GC-852)

**Owner:** `game/planet_evolution/planet_research.py` — **≠** Account-Forschung ([RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) / GC-825 `power_research_seconds`).

Definitionen: `pe_research_definitions` (Seed Migration `017`) → `get_research_def()` in `definitions.py`.

| Feld in Def | Rolle |
|-------------|-------|
| `base_cost_m` / `base_cost_c` | Kosten-Basis Stufe 1 |
| `cost_factor` | Exponential pro Zielstufe (Legacy-Kurve) |
| `base_time` | Zeit-Basis (Sekunden) |
| `tier` | Tech-Band (1, 2, …) — beeinflusst **nur** die Zeit, nicht die Kosten |
| `max_level` | Max. erreichbare Stufe pro Tech |

### Kosten (live)

```text
metal  = floor(base_cost_m × cost_factor^(target_level − 1))
crystal = floor(base_cost_c × cost_factor^(target_level − 1))
```

Funktion: `compute_planet_research_cost(tech_key, target_level)`.

Beispiel `industry_t1_automation` (800 / 400, `cost_factor = 1.5`), Ziel L3:  
metal = `800 × 1.5² = 1800`, crystal = `400 × 1.5² = 900`.

### Zeit (live)

```text
duration_seconds = max(1.0, base_time × 1.45^(tier − 1) ÷ planet_research_speed)
```

Funktion: `compute_planet_research_time(planet_id, tech_key, target_level, conn)`.

**Wichtig:** `target_level` fließt in die **Zeit** nicht ein — nur `tier` aus der Definition und der Speed-Multiplikator.

| Speed-Faktor | Quelle |
|--------------|--------|
| `planet_research_speed` | `game_settings` (Default 1.0) |
| Bonus | Planet-Flag `planet_research_speed_bonus` (additiv: `× (1 + bonus)`) |

Untergrenze: `1.0` s (technischer Safety-Floor, kein 30s-Balance-Cap — GC-622B).

### Queue

| Regel | Wert |
|-------|------|
| Limit | `game_settings.planet_research_queue_limit` (Default 2) + Flag `planet_research_queue_bonus` |
| Scheduling | Sequenziell; `finish_at` = max(now, letzter Job) + `duration` |
| Zahlung | Sofort metal/crystal beim Enqueue |
| Cancel | `cancel_planet_research_job` → `refund_planet_evolution_research_job` (GC-831) |
| Finish | `finish_planet_research_jobs` via `queue_engine` |

**Bewusst Legacy:** Planet-Tech nutzt weiterhin `cost_factor^level` — kein GC-821/GC-825 Power-Curve-Migration. Umbau wäre separates Balancing-Ticket, nicht GC-852.

---

## Kolonisierung

| Weg | Entry |
|-----|-------|
| Fleet | Mission `colonize` → `colonize_planet()` in service |
| API | `POST /api/planets/colonize` |

- Neue Planet-Row + `ensure_planet_evolution()`
- Koordinaten via [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)
- Limit: `game_settings.max_colonies_per_player` (Default 9)
- Start-Ressourcen: 500 metal, 250 crystal

### Legacy Planet Evolution Backfill

Optional maintenance script for missing `planet_dna` / `planet_mechanics` rows on older planets:

```bash
python scripts/backfill_planet_evolution_legacy.py --dry-run
python scripts/backfill_planet_evolution_legacy.py
```

**Gameplay (GC-976+):** World-Map-/Outpost-Gates blockieren **kein** normales Bauen. Kolonie-Limit = `min(admin_cap, evolution_cap)` — Slots über Genesis-Ark-Stufe (`expansion_slots_unlocked`), Admin-Cap als Hard-Cap.

---

## Routes

### Page

| Route | Rolle |
|-------|-------|
| `GET /planet-evolution` | Dashboard — **immer active planet** |

Template: `templates/planet_evolution.html` (Traits, Spec, Research, Events, Policies, History).

**Kein** In-Page-Planet-Switcher — nur Header ([PLANET_SCOPE.md](PLANET_SCOPE.md)).

### APIs

| Route | Methode | Rolle |
|-------|---------|-------|
| `/api/planets` | GET | Kolonie-Liste (Switcher) |
| `/api/planets/active` | POST | Active setzen + game-state |
| `/api/planets/<id>/state` | GET | Voller Evolution-Payload |
| `/api/planets/<id>/research` | GET | Planet-Tech Status |
| `/api/planets/<id>/research/start` | POST | Queue Planet-Tech |
| `/api/planets/<id>/research/choose` | POST | Locked choice |
| `/api/planets/<id>/specialization/pick` | POST | Spec wählen (Level ≥ 8) |
| `/api/planets/<id>/specialization/upgrade` | POST | Spec-Tier |
| `/api/planets/<id>/policies/activate` | POST | Policy aktivieren |
| `/api/planets/<id>/events/resolve` | POST | Event-Choice |
| `/api/planets/colonize` | POST | Kolonie anlegen |

Alle `<id>`-Mutationen: Owner-Check (`get_planet_owner_id == session user`).

---

## Integration andere Systeme

| System | Integration |
|--------|-------------|
| Resources | Tick auf Planet-Row; Trade Routes transferieren Ressourcen |
| Buildings | Planet-scoped wie üblich |
| Account Research | Getrennt — Lab-Level empire-wide für Account-Tech only |
| Fleet | Colonize-Mission, `seed_ark` Verbrauch |
| Galaxy | Koordinaten, Slot-Markierung |
| Ranking | Planet-Score in Galaxy-Meta |
| Overview | Teaser-Widget (`teaser.py`) |

---

## Gate

`evolution_schema_ready()` — prüft u. a. `planet_dna` + `pe_trait_definitions`.

Ohne Schema: `get_context_planet()` fällt auf Homeworld-only-Verhalten zurück.

---

## Neues Evolution-Feature

1. Definition in `pe_*` (Migration/Seed) oder Code-Definition
2. Consumer in `mechanics.py` / `tick.py`
3. API in `service.py` + Route in `app.py`
4. UI in `planet_evolution.html` + ggf. `main.js`
5. Test in `tests/test_planet_evolution*.py`

**Nicht:** Account-`research_levels` für Planet-spezifische Techs missbrauchen.

---

## Tests

```bash
python -m pytest tests/test_planet_evolution.py tests/test_planet_evolution_dashboard.py tests/test_planet_instancing.py -v
```

---

## Verwandte Docs

- [PLANET_SCOPE.md](PLANET_SCOPE.md)
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)

---

## Player Article

```yaml
---
codex_id: planet_evolution
band: II
difficulty: beginner
estimated_read: 5 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - planet_evolution_view
related_codex:
  - genesis_ark
  - expansion
  - planet_scope
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

Planet Evolution ist das Herz deines Imperiums. Entwickle Welten durch DNA, Entwicklungsstufe und Spezialisierung — und schalte damit neue Regionen frei.

## Summary

**Planet Evolution** ist die **pro-Welt-Progression**: DNA und Traits, Entwicklungsstufe/XP, Planet-Klasse, Planet-Tech (≠ Account-Forschung), Spezialisierung, Policies, Events, Discoveries und Trade Routes. Auf der **Genesis Ark** ist Evolution der zentrale Langzeit-Fortschritt; auf Kolonien formt sie den **Charakter** jeder Welt.

## Why

Genesis Colonies unterscheidet sich durch **Identität pro Welt** — nicht nur Gebäudelevel. Evolution entscheidet, welche Regionen erreichbar sind, welche Spezialisierungen möglich werden und wie Welten ins Imperium passen. Gebäude und Account-Forschung sind der Motor **unterhalb** dieser Schicht.

## How it works

- Öffne **Planet Evolution** für die **aktive Welt** (Header-Switcher).
- **DNA & Traits** prägen Forschung, Events und Spezialisierungsoptionen.
- **Entwicklungsstufe** der Genesis Ark schaltet Expansion Sites frei (siehe Expansion).
- Ab höherer Entwicklung: **Spezialisierung** (dauerhafte planetare Ausrichtung), **Policies**, narrative **Events** mit Entscheidungen.
- **Planet-Tech** — Forschung nur für diese Welt, eigene Queue.
- **Trade Routes** verbinden Kolonien sichtbar mit dem Imperium.
- **Ascension** — separater Langzeit-Pfad (siehe Ascension-Artikel).
- Queues für Planet-Tech und Ascension erscheinen in den jeweiligen Cards.

## Related Systems

- genesis_ark
- expansion
- planet_scope
- research
- fleet

## Commander Tips

- Entwicklungsstufe der Ark vor blindem Minen-Push — sie öffnet die Command Map.
- Spezialisierung ist dauerhaft; vor der Wahl im Codex und in der UI nachlesen.
- Planet-Tech und Account-Forschung nicht verwechseln.

## FAQ

**Warum unterscheidet sich meine Welt von der Ark?**
Jede Welt hat eigene DNA, Traits und optional eigene Spezialisierung.

**Was ist Planet-Tech?**
Weltgebundene Forschung in Planet Evolution — nicht der Account-Tech-Tree.

## Discord Summary

**Planet Evolution — Identität und Fortschritt pro Welt**

DNA, Entwicklungsstufe, Spezialisierung, Events, Planet-Tech. Zentrum auf der Genesis Ark; Kolonien werden Charakter-Welten. Schaltet Regionen und Expansion frei. ≠ Account-Forschung.

---

## Player Article

```yaml
---
codex_id: ascension
band: IV
difficulty: advanced
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
routes:
  - planet_evolution_view
related_codex:
  - planet_evolution
  - genesis_ark
terminology: GENESIS_TERMINOLOGY
unlock:
  type: homeworld_level
  value: 15
teaser_key: codex_unlock_ascension_teaser
---
```

## Quick Help

**Ascension** ist Langzeit-Fortschritt auf der Genesis Ark — eine Queue, die über Planet Evolution das Endgame des Imperiums vorbereitet.

## Summary

Ascension ist ein **Langzeit-Queue-System** auf der Genesis Ark: Schritte in Planet Evolution, Fortschritt über die Ascension-Queue — nicht ein schneller Button-Fortschritt.

## Why

Ascension bündelt Endgame-Entscheidungen am **Imperiums-Hauptsitz** — konsistent mit der Regel, dass die Ark nicht durch Kolonien ersetzt wird. Es ergänzt Spezialisierung und Strategic Worlds um einen imperiumsweiten Horizont.

## How it works

- Erreichbar über **Planet Evolution** auf der Genesis Ark, wenn Freischaltung (Entwicklungsstufe 15) aktiv ist.
- Ascension-Jobs laufen in der **Ascension-Queue** — eigene Card neben Planet-Tech, sequenziell wie andere Queues.
- Schritte sind **Langzeit-Investitionen**: Kosten und Dauer in der UI; Zahlen nur serverseitig, nicht im Codex.
- Erfordert vorbereitete Planet Evolution (Spezialisierung, Policies, stabile Ark) — kein Early-Game-System.
- Ascension ergänzt **Strategic Worlds** und Imperiums-Directives — kein Ersatz für Kolonie-Ausbau.
- Queue-Zeit mit Planet-Tech und Baujobs der Ark koordinieren; nur eine Ascension-Queue parallel zum Planet-Tech-Pfad.
- Details pro Stufe: Planet Evolution UI und Queue-Cards — nicht in diesem Codex-Artikel.

## Related Systems

- planet_evolution
- genesis_ark
- strategic_worlds

## Commander Tips

- Ascension erst planen, wenn Kern-Evolution und Imperium stabil stehen.
- Queue-Zeit mit anderen Planet-Jobs koordinieren.

## FAQ

**Kann jede Kolonie Ascension starten?**
Fokus und Design: Genesis Ark als Hauptsitz — prüfe Freischaltung in der UI der aktiven Welt.

## Discord Summary

**Ascension — Langzeit auf der Genesis Ark**

Queue-basierter Endgame-Pfad in Planet Evolution. Imperiums-Horizont am Hauptsitz, nicht auf Outposts.
