# Planet Evolution System

Per-Planet Progression: DNA, Traits, Planet-Forschung, Specialization, Policies, Events (v1.5.3).

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

## Kolonisierung

| Weg | Entry |
|-----|-------|
| Fleet | Mission `colonize` → `colonize_planet()` in service |
| API | `POST /api/planets/colonize` |

- Neue Planet-Row + `ensure_planet_evolution()`
- Koordinaten via [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)
- Limit: `game_settings.max_colonies_per_player` (Default 9)
- Start-Ressourcen: 500 metal, 250 crystal

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
