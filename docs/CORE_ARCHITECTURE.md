# GC-000 — Core Architecture Enforcement

> **Genesis Colonies bevorzugt Konsistenz über Komfort.**  
> Lieber ein bestehendes kanonisches System erweitern, als ein zweites ähnliches System einzuführen.

Verbindliche Architekturvorgaben für Genesis Colonies. **Vorrang vor Feature-Komfort, Schnelllösungen und Legacy-Verhalten.**

Jedes Ticket prüft vor Implementierung:

| Dokument | Thema |
|----------|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Gesamtüberblick |
| [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) | Dieses Dokument (Golden Rule) |
| [STATE_AJAX.md](STATE_AJAX.md) | Live-State, Polling |
| [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) | Navigation, Actions, Lifecycle |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | Aktiver Planet |
| [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) | Queues, Finish/Cancel |

---

## 1. Single Source of Truth

Der Server ist immer die einzige Wahrheit.

| Verboten | Erlaubt |
|----------|---------|
| Eigene Frontend-Berechnungen als Wahrheit | Anzeige, Formatierung |
| Client-Queue-/Ressourcen-/Flugzeit-/Kampf-Math | Countdown- und Progressbar-Darstellung aus Server-Timestamps |
| Parallele Client-States | `GC.lastState` als Cache von `/api/game-state` |

Formeln: [EFFECTS.md](EFFECTS.md) (`EffectResolver`). UI patcht nur via `applyGameStateData()` / `applyActionState()`.

---

## 2. No Full Reload

Genesis Colonies ist vollständig AJAX/PJAX-basiert. Grundsatz: **Kein Reload, wenn technisch vermeidbar.**

| Verboten | Erlaubt |
|----------|---------|
| `window.location.reload()`, `location.reload()` | Login, Logout, Datei-Download, externe Links |
| `window.location.href = …`, `location.href = …` (Navigation) | Lesen von `location.href` / `history.replaceState` |
| Full-Page-Navigation für Shell-Routen | Dokumentierter Fatal-Recovery-Fallback (siehe [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)) |

Pflicht-APIs: `GC.navigateTo()`, `GC.reloadCurrentPage()`, `GC.fetchGameAction()`, `GC.refreshGameState()`.

---

## 3. Shell First

`templates/base.html` bleibt permanent. Nur `#main-content` wird ersetzt.

### Navigation Shell (GC-806)

Ingame-Desktop-Shell — Layout **immer**:

```text
Left Sidebar (Gameplay) | Main (#main-content) | Right Sidebar (Meta)
```

Zusätzlich: Header, Resource Bar, Bottom Utility Dock (Support, Tickets, legal, Discord, Wiki, Tchat, Version).

| Verboten | Erlaubt |
|----------|---------|
| Route-basierter Wide-Mode (rechte Sidebar auf Fleet/Galaxy/Ranking ausblenden) | Content passt sich an (`min-width: 0`, internes Scrollen in Panels/Tabellen) |
| Sidebars pro Seite togglen, um Content-Breite zu erzwingen | Tablet 992–1279px: rechte Sidebar als Drawer |
| Paralleles Layout-System neben `.gc-layout--dual` | Ein Shell-Grid in `base.html`; PJAX tauscht nur `#main-content` |

**Regel:** Navigation niemals auf Desktop verstecken — breite Module passen sich an, nicht die Shell.

Details: [ARCHITECTURE.md](ARCHITECTURE.md) — Navigation Shell (GC-806).

Diese Routen dürfen **niemals** die komplette Anwendung neu laden:

`Overview` · `Buildings` · `Research` · `Galaxy` · `Fleet` · `Defense` · `Trader Hub` · `Messages` · `Alliance` · `Planet Evolution`

Details: [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

---

## 4. State Architecture

Exakt ein globaler Spielzustand — Quelle: **`GET /api/game-state`**.

| Verboten | Erlaubt |
|----------|---------|
| Modul-eigenes Polling (Spiel-State) | Modul-UI aus `GC.lastState` |
| Eigene Ressourcen-/Queue-/Planet-Caches als Wahrheit | Page-spezifische DOM-Hooks |

Chat (`static/js/chat.js`) hat eigenes Polling für Chat-Nachrichten — **kein** Ersatz für game-state (Ausnahme dokumentiert in [STATE_AJAX.md](STATE_AJAX.md)).

---

## 5. Planet Scope Contract

Single Source of Truth: `players.active_planet_id` → **`get_context_planet()`**.

| Verboten | Erlaubt |
|----------|---------|
| Session-basierter Planet | `POST /api/planets/active` |
| Homeworld-Hardcoding in Features | Homeworld nur als Fallback in Resolver |
| Eigene Planetensysteme | `resolve_owned_planet_id()` für explizite `planet_id` |

Details: [PLANET_SCOPE.md](PLANET_SCOPE.md).

---

## 6. Queue Architecture

Alle Queues (Build, Research, Shipyard, Fleet, Defense, Planet Evolution, zukünftige) folgen [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md).

Zentraler Finisher: `game/queue_engine.py` — `finish_due_work_once()` / `finish_due_work()`.

---

## 7. AJAX Action Contract

Jede Spieler-Mutation liefert `{ "ok": true, "state": { … } }` (game-state payload). Frontend: **`applyActionState()`** — kein Reload nach Action.

**Bekannte Ausnahmen (GC-512D):** Shipyard build/cancel und Teile der Fleet-GET-APIs nutzen `{ ok, data }` via `fleet_ok()` — Client: `applyShipyardState`. Siehe [STATE_AJAX.md](STATE_AJAX.md).

---

## 8. Frontend Lifecycle

PJAX-sicher: `GC.registerCleanup(…)` für Interval, Timeout, rAF, Fetch, Listener. Bei Seitenwechsel: **`GC.cleanupPage()`**.

---

## 9. Polling Contract

Erlaubte Spiel-State-Quelle: **`/api/game-state`** (Singleton in `GC.polling`). Kein Modul-Parallel-Polling für Ressourcen/Queues.

---

## 10. UI Synchronisation

Nach Mutation: **Server → API → State → UI**. Die UI rät nie.

---

## 11. Future Systems

Combat, Defense, Recycler, Logistics, Alliance Warfare, Marketplace, Moon, Events, Expeditions, NPC — müssen kompatibel sein:

- Kein eigener Wahrheits-State
- Kein eigenes Spiel-Polling
- Keine parallele Queue-Engine
- Keine Reload-Abhängigkeit

---

## 12. Testing Requirements

| Domäne | Tests |
|--------|-------|
| Queues | enqueue, cancel, finish, race, near-finish enqueue, state sync |
| UI/PJAX | Navigation, Planetwechsel, Back/Forward, Polling, Cleanup |

```bash
python -m pytest tests/test_core_architecture_enforcement.py tests/test_race_conditions.py tests/test_game_state_live.py -v
```

---

## 13. Golden Rule

Eine Lösung ist **falsch**, wenn sie:

- Reloads für normale Spielnavigation braucht
- Mehrere Wahrheiten erzeugt
- Frontend-Mathematik für Mechanik einführt (Regel 16)
- Parallele States, Queues oder Domänen-Systeme einführt (Regel 15)
- Planet Scope umgeht
- Keinen klaren System-Owner hat (Regel 17)

→ Überarbeiten, nicht mergen.

---

## 15. No Parallel Systems

Es darf **immer nur ein kanonisches System** pro Domäne geben.

| Verboten (Beispiele) | Kanonisch |
|----------------------|-----------|
| `shipyard` + `orbital_shipyard` als parallele Keys/Tabellen | `orbital_shipyard` (+ Legacy-Alias beim Lesen) |
| `fleet_state` + `fleet_movements` | `fleet_movements` |
| `planet_session` + `active_planet_id` | `players.active_planet_id` → `get_context_planet()` |
| `combat_v1` + `combat_v2` | `game/combat.py` (`simulate_battle`) |

**Ersetzen statt duplizieren:**

```text
Migration → Alias/Adapter → Entfernen des Alten
```

**Niemals:**

```text
altes System + neues System gleichzeitig (ohne dokumentierten Übergang mit Enddatum)
```

Neue Features erweitern den Owner (Regel 17), sie legen kein Parallel-Modul an.

---

## 16. No Duplicate Math

Server und Client dürfen dieselbe Mechanik **nicht** unabhängig berechnen. Typisches Symptom: Progress 97 % → 100 % → 92 % → 98 %.

| Verboten im Frontend (`static/`) | Autoritative Berechnung (Python) |
|----------------------------------|----------------------------------|
| Ressourcen-Produktion / Cap | `game/production_formula.py`, `game/resources.py` — [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md) |
| Flugzeit / Fleet-Speed / Fuel | `game/fleet_calc.py`, `game/fleet.py` |
| Kampf / Loot / Debris | `game/combat.py` |
| Queue-Finish / Dauer / Kosten | `game/queue_engine.py`, Domänen-Module (`buildings`, `research`, `shipyard_queue`, …) |

**Erlaubt im Frontend:** Anzeige, Formatierung, Countdown aus Server-`finish_time` / `start_time`, Progressbar = `(server_now - start) / (finish - start)` mit `GC.getServerNow()` — **ohne** eigene Formeln für Produktion, Speed oder Kampf.

Regel 1 (Single Source of Truth) gilt; Regel 16 macht Duplicate-Math explizit prüfbar.

---

## 17. Every Feature Needs An Owner

Für jede Domäne gibt es **genau eine** Antwort auf „Wo gehört das hin?“. Neue Systeme ergänzen diese Tabelle im selben PR.

| System | Owner (Modul) | Doc |
|--------|-----------------|-----|
| Queues (Finish-Pass) | `game/queue_engine.py` | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |
| Queue Card UX (Presentation Adapter) | `game/queue_card.py` | [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) |
| Live-State / Poll-Payload | `app.py` (`_build_game_state_payload`) + `game/logic.py` + `game/live_state.py` | [STATE_AJAX.md](STATE_AJAX.md) |
| Planet Scope | `game/planet_evolution/repository.py` (`get_context_planet`) | [PLANET_SCOPE.md](PLANET_SCOPE.md) |
| Ressourcen / Tick | `game/resources.py` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| Produktionsformeln | `game/production_formula.py` | [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md) |
| Economy-Rebalance (GC-821) | `game/economy_balance.py` | [GC-821_ECONOMY_REBALANCE.md](GC-821_ECONOMY_REBALANCE.md) · [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md) |
| Queue refunds (GC-831) | `game/queue_refund.py` | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |
| Technical data display (GC-823) | `game/technical_data.py` | [GC-823_TECHNICAL_DATA.md](GC-823_TECHNICAL_DATA.md) |
| Live economy QA (GC-822) | `game/economy_live_audit.py` | [GC-822_LIVE_ECONOMY_QA.md](GC-822_LIVE_ECONOMY_QA.md) |
| Effekte / Energie / Storage / Zeit | `game/effects/` (`EffectResolver`) | [EFFECTS.md](EFFECTS.md) |
| Buildings / Bau-Queue | `game/buildings.py` | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| Account-Forschung | `game/research.py` | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |
| Shipyard-Queue | `game/shipyard_queue.py`, `game/shipyard.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet / Missionen | `game/fleet.py`, `game/fleet_calc.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet world-native targets (GC-590A) | `game/fleet_target.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet origin scope audit (GC-557C) | `game/fleet_origin.py` | [GC-557_GLOBAL_TIMER_AUDIT.md](GC-557_GLOBAL_TIMER_AUDIT.md) |
| Defense-Queue | `game/defense.py`, `game/defense_api.py` | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) |
| Combat | `game/combat.py` | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Galaxy (Legacy system view) | `game/galaxy.py` | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| World Map (command_map payload, layout) | `game/planet_evolution/command_map.py` | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |
| Shared world presence (all empires on map) | `game/planet_evolution/world_map.py` | [GC-571_SHARED_WORLD_PRESENCE.md](GC-571_SHARED_WORLD_PRESENCE.md) |
| Sector grid geography (Command Map chunks) | `game/planet_evolution/sector_grid.py` | GC-580A; viewport chunks via `GET /api/command-map/sectors` (GC-580B) |
| Strategic worlds (free field presentation) | `game/planet_evolution/strategic_worlds.py` | [GC-581_STRATEGIC_WORLDS.md](GC-581_STRATEGIC_WORLDS.md) |
| World colonization from map | `game/planet_evolution/world_colonization.py` | [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) — GC-582A claims |
| Location role actions (Map → Routes) | `game/planet_evolution/location_actions.py` | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |
| Command Center panel (own colony snapshot) | `game/planet_evolution/command_center.py` | [GC-592_COMMAND_CENTER_PANEL.md](GC-592_COMMAND_CENTER_PANEL.md) |
| Planet Evolution | `game/planet_evolution/` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| Galactic Directives | `game/galactic_directives/` | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) |
| Galactic Diplomacy | `game/galactic_diplomacy/` | [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md) |
| Referrals | `game/referrals.py` | GC-703 |
| Ranking scores / ranks (batch) | `game/ranking_worker.py` → `game/ranking.py` | `POST /api/internal/cron/ranking` (HTTP cron on web service); local: `scripts/run_ranking_worker.py` |

**Ticket-Check:** Domäne identifizieren → nur Owner-Modul (+ Routes/`app.py`) ändern → kein zweites Modul für dieselbe Wahrheit.

---

## Zielzustand

Verhalten wie eine moderne SPA: Shell bleibt, PJAX-Navigation, AJAX-Actions, serverseitige Wahrheit, deterministische Queues, konsistenter Planet Scope, kein State-Drift, neue Module brechen bestehende nicht.
