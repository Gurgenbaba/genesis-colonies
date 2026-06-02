# Genesis Colonies — Entwicklungsworkflow

Kurzanleitung für Tickets, Docs und Cursor. **Kein Projekt-Vollscan** — Master-Docs lesen, Ticket-Scope bearbeiten.

---

## Ebene 0 — Epics

Epics beschreiben nur das Ziel. **Niemals direkt implementieren.**

| Epic | Ziel | Doc |
|------|------|-----|
| EPIC-01 | Planet Scope & Multi-Kolonie | [PLANET_SCOPE.md](PLANET_SCOPE.md) |
| EPIC-02 | Fleet System | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| EPIC-03 | Galaxy System | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| EPIC-04 | Economy & Trader Hub | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| EPIC-05 | Planet Evolution | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| EPIC-06 | Buildings | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| EPIC-07 | Research (Account-Tech) | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |

Epic → in **3–5 Tickets** zerlegen. Siehe [EPICS.md](EPICS.md).

---

## Ebene 1 — Master-Docs

Vor jeder Änderung die relevanten Docs lesen:

| Dokument | Wann |
|----------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architektur, Module, APIs |
| [ROADMAP.md](ROADMAP.md) | Status, Phasen, Schulden |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | Aktiver Planet, Switch, Scope |
| [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | Ressourcen, Exchange, Fuel |
| [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) | Gebäude, Bau-Queue |
| [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) | Account-Forschung |
| [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | Flotten, Schiffe, Missionen |
| [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | Kampf-Resolver, Loot, Debris, Reports |
| [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) | Koordinaten, Systemansicht |
| [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | DNA, Planet-Tech, Events |
| [EFFECTS.md](EFFECTS.md) | EffectResolver, Formeln |
| [STATE_AJAX.md](STATE_AJAX.md) | Polling, PJAX, Live-State |

**Regel:** Architektur-Entscheidungen aus Docs respektieren. Bei Änderung → Doc mit aktualisieren.

---

## Ebene 2 — Tickets

Format: **GC-XXX Titel** (Micro: **GC-XXXA**)

Vorlage: [TICKET_TEMPLATE.md](TICKET_TEMPLATE.md)

| Regel | Detail |
|-------|--------|
| Ein Problem pro Ticket | Kein Sammel-Fix |
| Max. 3–5 Dateien | Im Ticket explizit listen |
| Kein Scope-Drift | Kein Refactor außerhalb |
| Größe | 500–1500 Tokens; max. 3000 |

---

## Ebene 3 — Implementierung

```
1. Relevantes Master-Doc lesen
2. Nur Ticket-Dateien öffnen
3. Fix / Feature umsetzen
4. Tests (nur wenn sinnvoll / gefordert)
5. Ausgabeformat (siehe unten)
```

### Verboten

- „Analysiere das komplette Projekt“
- Ungefragte Architekturänderungen
- Parallele Systeme (z. B. zweite Fleet-Queue, `shipyard` + `orbital_shipyard`)

### Erlaubt

- Nur genannte Dateien bearbeiten
- Legacy-Mapping statt Duplikation
- Migration statt Schema-Hack nur in `init_db()`

---

## Ausgabe nach Ticket

```markdown
## Root Cause
...

## Changed Files
...

## Tests
...

## Ergebnis
...
```

Kurz. Keine Projektzusammenfassung.

---

## Tests

```bash
python -m pytest tests/ -v          # gesamt (513)
python -m pytest tests/test_fleet.py -v   # domänenspezifisch
```

| Domäne | Tests |
|--------|-------|
| Queues / Race | `test_race_conditions.py`, `test_queue_engine.py` |
| Live-State | `test_game_state_live.py`, `test_static_live_updates.py` |
| Planet Scope | `test_planet_instancing.py`, `test_header_planet_switcher.py` |
| Evolution | `test_planet_evolution*.py` |
| Fleet / Galaxy | `test_fleet.py`, `test_galaxy.py` |
| Economy | `test_exchange.py`, `test_fuel_exchange.py`, `test_trader_hub.py` |

---

## Architektur-Kern (Merken)

- **PJAX** — Shell bleibt, `#main-content` wird getauscht
- **Planet Scope** — `players.active_planet_id` → `get_context_planet()`
- **Queue Engine** — `game/queue_engine.py`, single finish pass pro Request
- **EffectResolver** — autoritative Formeln, kein Frontend-Math
- **Kanonische Keys** — `orbital_shipyard`, ein Fleet-State in `fleet_movements`

---

## Verwandte Docs

- [CONTRIBUTING.md](CONTRIBUTING.md) — Code-Stil, Migrationen, PR
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle QA
