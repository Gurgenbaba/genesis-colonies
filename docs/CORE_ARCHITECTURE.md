# GC-000 — Core Architecture Enforcement

> **Genesis Colonies bevorzugt Konsistenz über Komfort.**  
> Lieber ein bestehendes kanonisches System erweitern, als ein zweites ähnliches System einzuführen.

Verbindliche Architekturvorgaben für Genesis Colonies. **Vorrang vor Feature-Komfort, Schnelllösungen und Legacy-Verhalten.**

Jedes Ticket prüft vor Implementierung:

| Dokument | Thema |
|----------|--------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Gesamtüberblick |
| [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) | Dieses Dokument (Golden Rule) |
| [BETA_GATE.md](BETA_GATE.md) | Alpha-Exit, Core Architecture Freeze, Beta-Governance |
| [STATE_AJAX.md](STATE_AJAX.md) | Live-State, Polling |
| [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) | Navigation, Actions, Lifecycle |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | Aktiver Planet |
| [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) | Queues, Finish/Cancel |

**Agent-Regel (always apply):** [.cursor/rules/no-dead-code-no-bloat.mdc](../.cursor/rules/no-dead-code-no-bloat.mdc) — Regel 19: keine toten Helper, keine parallelen Duplikate; ersetzen und entfernen im selben Ticket.

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
Left Sidebar (Gameplay) | Main (#main-content) | Meta | Planet Registry
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

**Shipyard (GC-512D):** build/cancel nutzen `fleet_ok()` + `body["state"]` → `{ ok, state }` (+ optional `data` für Stocks/Labels). Client ist **state-first**: `applyActionState` wenn `res.state`; `applyShipyardState` nur bei `res.data`. Fleet-GET-APIs können weiter `{ ok, data }` sein. Siehe [STATE_AJAX.md](STATE_AJAX.md).

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
- Kolonien/Welten außerhalb des Expansion-Protocols erzeugt (Regel 18)
- Neue Helper neben alter Logik einführt, ohne alte Call-Sites zu migrieren und Toten Code zu entfernen (Regel 19)

→ Überarbeiten, nicht mergen.

---

## 18. Expansion Creates Worlds Through Protocol Only

> **Neue Systeme dürfen keine Kolonien erzeugen. Sie dürfen nur den Fortschritt einer Welt verändern.**

Design-Charta: [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) (EPIC-15).

| Owner | Darf |
|-------|------|
| **Fleet** | Seed Ark transportieren |
| **World colonization** (`world_colonization.py`) | Claim anlegen; Outpost-Planet-Row im Protocol-Flow |
| **Establishment / Queue Engine** | Etablierungs-Meilensteine abschließen |
| **Buildings** | Infrastruktur für Meilensteine bauen |
| **Planet Evolution** | Welt entwickeln (DNA, Spec, Events) |
| **Command Map** | Fortschritt visualisieren; kein eigener Colonize-Pfad |

**Verboten:** Beliebiges Modul ruft `colonize_planet()` oder legt `planets`-Rows an, ohne den Expansion-Protocol-Flow (Claim → Fleet → Outpost → Meilensteine → Kolonie). Kein paralleler „+1 Planet"-Pfad (Astrophysik-Slots, `max_colonies` als Gameplay-Gate).

`expansion_phase` ist **abgeleitet** (Resolver), nicht als isolierter Status, der out-of-sync hängen bleibt.

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
| Technical data display (GC-823) | `game/technical_data.py` | [GC-823_TECHNICAL_DATA.md](GC-823_TECHNICAL_DATA.md) · [TECHCARD_UX.md](TECHCARD_UX.md) |
| Live economy QA (GC-822) | `game/economy_live_audit.py` | [GC-822_LIVE_ECONOMY_QA.md](GC-822_LIVE_ECONOMY_QA.md) |
| Effekte / Energie / Storage / Zeit | `game/effects/` (`EffectResolver`) | [EFFECTS.md](EFFECTS.md) |
| Buildings / Bau-Queue | `game/buildings.py` | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| Account-Forschung | `game/research.py` | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |
| Shipyard-Queue | `game/shipyard_queue.py`, `game/shipyard.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet / Missionen | `game/fleet.py`, `game/fleet_calc.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet global tick (offline) | `game/fleet_worker.py` → `game/fleet.py` | `POST /api/internal/cron/fleet-tick`; piggyback ranking cron |
| Queue global tick (offline) | `game/tick_runner.py` → `game/queue_engine.py` | `POST /api/internal/cron/queue-tick`; `scripts/run_game_worker.py`; `GC_GAME_WORKER_PRIMARY` |
| Fleet world-native targets (GC-590A) | `game/fleet_target.py` | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Fleet origin scope audit (GC-557C) | `game/fleet_origin.py` | [GC-557_GLOBAL_TIMER_AUDIT.md](GC-557_GLOBAL_TIMER_AUDIT.md) |
| Defense-Queue | `game/defense.py`, `game/defense_api.py` | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) |
| Combat | `game/combat.py` | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| Galaxy (system view — player default) | `game/galaxy.py` | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| World Map (command_map — **Dev-Preview only**, GC-593) | `game/planet_evolution/command_map.py` | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |
| Shared world presence (Dev-Preview map layout) | `game/planet_evolution/world_map.py` | [GC-571_SHARED_WORLD_PRESENCE.md](GC-571_SHARED_WORLD_PRESENCE.md) |
| Sector grid geography (Command Map chunks) | `game/planet_evolution/sector_grid.py` | GC-580A; viewport chunks via `GET /api/command-map/sectors` (GC-580B) |
| Strategic worlds (free field presentation) | `game/planet_evolution/strategic_worlds.py` | [GC-581_STRATEGIC_WORLDS.md](GC-581_STRATEGIC_WORLDS.md) |
| World colonization (`world_key` — Dev/Legacy) | `game/planet_evolution/world_colonization.py` | [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) — **kein Blocker** für Galaxy-Gameplay (Regel 18) |
| Location role actions (Map → Routes) | `game/planet_evolution/location_actions.py` | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |
| Command Center panel (own colony snapshot) | `game/planet_evolution/command_center.py` | [GC-592_COMMAND_CENTER_PANEL.md](GC-592_COMMAND_CENTER_PANEL.md) |
| `expansion_phase` Resolver (derived) | `game/planet_evolution/expansion_phase.py` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) |
| `expansion_phase` / Establishment | `game/planet_evolution/expansion_phase.py` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) |
| Expansion Sites / Gates | `game/planet_evolution/expansion_gates.py` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) |
| Expansion Protocol (dual-gate, outpost, establishment) | `game/planet_evolution/expansion_protocol.py` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) — `can_found_colony()` für Galaxy; Gates/Outpost **Legacy** (Regel 18) |
| Expansion Phase (derived) | `game/planet_evolution/expansion_phase.py` | [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) |
| Planet Evolution | `game/planet_evolution/` | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| Galactic Directives | `game/galactic_directives/` | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) |
| Imperial Directives (player High Command) | `game/directives/` | [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) |
| Galactic Diplomacy | `game/galactic_diplomacy/` | [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md) |
| Referrals | `game/referrals.py` | GC-703 |
| Resource score (kanonischer Punktwert) | `game/resource_score.py` → `game/ranking.py` | [SCORE_SYSTEM.md](SCORE_SYSTEM.md) |
| Ranking scores / ranks (batch) | `game/ranking_worker.py` → `game/ranking.py` | [SCORE_SYSTEM.md](SCORE_SYSTEM.md) · `POST /api/internal/cron/ranking` |
| Definition / settings cache | `game/definition_cache.py` | Process + optional Redis (`GC_REDIS_URL`); never SoT for queues/fleets |
| Vote re-engagement (inactive players) | `game/vote_reengagement.py` | Piggyback on ranking HTTP cron (30 min guard); optional `POST /api/internal/cron/vote-reengagement`; local: `scripts/run_vote_reengagement.py` |
| Game Rules (Fair Play, PvP-Policy, Support) | `game/game_rules_panel.py` (UI) · Enforcement verteilt | [GAME_RULES.md](GAME_RULES.md) |
| Genesis Codex (loader, unlocks) | `game/codex.py` | [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) |
| Knowledge generator (Player Blocks → catalog/locales) | `scripts/generate_knowledge.py` | [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) |
| Codex UI surfaces | `templates/partials/codex_*.html`, `special_panel.html` | [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) |
| Collector Exchange (Offers, Redeem, Stats) | `game/collector_exchange.py`, `game/collector_catalog.py` | [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md) |
| Collector Prestige (Milestones, Titles) | `game/collector_prestige.py` | [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md) |
| Alliance Hub (identity, pool, projects, diplomacy) | `game/alliance.py`, `game/alliance_catalog.py` | [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md) |
| Imperium Timekeeper (Zeitkonto, manuelles Einsetzen) | `game/timekeeper.py` | [TIMEKEEPER_SYSTEM.md](TIMEKEEPER_SYSTEM.md) |
| Human duration labels (y/mo/w/d/h/min/s) | `game/time_format.py` → Jinja `fmt_duration`, `GC.formatDurationHuman` | Adaptive ladders; never `mo`+`w`; season-scale uses days |
| World Boss Events (shared HP PvE, contribution, LiveOps) | `game/world_boss.py` | [WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) |
| Galaxy Asteroid Belt (temporary harvest fields) | `game/asteroids.py` | [ASTEROID_SYSTEM.md](ASTEROID_SYSTEM.md) |
| Pirate Ecosystem (Heat, bases, player-like AI, Bot-Log) | `game/pirates/` | [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md) |
| Login Attendance (30-day calendar) | `game/login_rewards.py` | [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) |
| Battle Pass Season (Free/Premium tracks) | `game/battle_pass.py` | [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) |
| Premium Entitlement | `game/premium_entitlements.py` | [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) / [PAYMENT_SHOP.md](PAYMENT_SHOP.md) |
| Shop Catalog + Fulfill | `game/shop.py` | [PAYMENT_SHOP.md](PAYMENT_SHOP.md) |
| Payment Providers (Stripe/PayPal) | `game/payment_providers.py` | [PAYMENT_SHOP.md](PAYMENT_SHOP.md) |
| Player-card season cosmetics (themes/badges/auras/flairs) | `game/playercard.py` unlock APIs | Base themes always free; Season keys via BP |

**Ticket-Check:** Domäne identifizieren → nur Owner-Modul (+ Routes/`app.py`) ändern → kein zweites Modul für dieselbe Wahrheit.

---

## 19. No Dead Code / No Bloat

> **Wenn eine Änderung eine neue Funktion braucht, muss sie alte Duplikat-Logik reduzieren — nicht vermehren.**

Erzwingt Regel 15/17 auf Code-Ebene: keine zweite Hilfsfunktion neben dem Owner, kein Legacy-Pfad ohne dokumentierten Übergang.

| Pflicht bei Änderung | Verboten |
|----------------------|----------|
| Bestehenden Owner prüfen und erweitern | Neue Funktion + alte unbenutzt liegen lassen |
| Neue Funktion nur mit Migration aller Call-Sites + Entfernen/Deprecate im selben Ticket | Gleiche Business-Logik in zwei Modulen |
| Toten Code löschen (Imports, Handler, Template-Blöcke, doppelte CSS) | Wrapper-Ketten ohne echten Zweck |
| `grep` nach alten Symbolen vor Abschluss | Tests nur an Nebenfunktion, alter Produktpfad bleibt |

**Typische Owner-Duplikate (nicht erneut einführen):** Queue-Logik, Fleet-Send, Preset-Engine, Production/ROI, Toast/Notify, Planet-/Galaxy-Gates.

**Adapter nur mit:** Ticketnummer/Enddatum, Tests für alt+neu, klarer Entfernungsperspektive.

**Ticket-Report (zusätzlich zu Root Cause / Tests):**

- Welche alte Logik wurde ersetzt?
- Welche alte Logik wurde entfernt?
- Welche alten Call-Sites wurden aktualisiert?
- Welche Suche wurde gemacht, um Dead Code auszuschließen?

Volltext (Cursor always-apply): [.cursor/rules/no-dead-code-no-bloat.mdc](../.cursor/rules/no-dead-code-no-bloat.mdc).

---

## 18. Galaxy-First Gameplay (GC-976)

**Verbindliche Regel:** Die klassische **Galaxy** (Koordinaten, Fleet, Buildings) ist der aktive Hauptspielpfad. World Map, Outpost, Frontier und Expansion-Site-Code sind **Legacy/Experiment** und dürfen **keine aktive Gameplay-Action blockieren**.

| Kanonisch (normales Gameplay) | Legacy / Dev-Preview (darf nicht sperren) |
|-------------------------------|-------------------------------------------|
| `game/galaxy.py` — Systemansicht, leere Slots | `game/planet_evolution/command_map.py` — Command Map |
| `game/fleet.py` — Kolonisierung per Koordinaten / Fleet | `game/planet_evolution/world_colonization.py` — `world_key`-Binding |
| `game/buildings.py` — Bau-Queue ohne Outpost-Gates | `expansion_protocol.is_building_allowed_in_outpost()` — **nicht** im Build-Flow |
| `can_found_colony()` / `check_planet_cap_available()` | `can_found_expansion_world()` / `evaluate_expansion_gates()` — nur Map/Inspector |

### Gebäudebau

- **Verboten:** Normale Gebäude über `world_key`, `outpost`, `expansion_site`, `frontier_state` oder Establishment-Flags sperren.
- **Owner:** `game/buildings.py` → `queue_build_for_planet()` — keine Aufrufe von Outpost-/World-Map-Gates.
- **Verbotene Block-Reasons im Build-Flow:** `outpost_*`, `frontier_*` (sowie jede Expansion-Site-Gate-Reason).

### Kolonisierung (Galaxy / Fleet)

- **Kolonie-Slots** kommen aus **Planet Evolution** (Genesis-Ark-Stufe / `expansion_slots_unlocked`), **ohne** World-Map-Gates.
- **Effective limit:** `min(admin_cap, evolution_cap)` — Implementierung: `can_found_colony()` in `expansion_protocol.py`, delegiert via `check_planet_cap_available()` in `game/logic.py`.
- **Admin-Cap** (`max_colonies_per_player`) ist nur **Hard-Cap** → Reason `colony_limit_reached`.
- **Fehlender Evolution-Slot** → Reason `planet_evolution_colony_slot_required`.
- **Verboten im Galaxy-/Fleet-Colonize-Flow:** `colonize_requires_expansion_site`, `outpost_*`, `expansion_gate_*`, `expansion_slot_cap_reached`, `expansion_admin_ceiling_reached`, `frontier_*`.
- Legacy-Args (`world_key`, `world_type`, `site_key`) an `check_planet_cap_available()` werden **ignoriert** — Galaxy-Kolonisierung prüft nur Evolution + Admin.

### Wartung / Backfill

- `scripts/backfill_planet_evolution_legacy.py` — fehlende EVO-Rows auf Alt-Planeten (Maintenance, kein Gameplay-Gate).

Details: [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — Abschnitt *Galaxy-First Gameplay*.

Regression: `tests/test_galaxy_gameplay_contract.py`, `tests/test_expansion_protocol.py`.

---

## Zielzustand

Verhalten wie eine moderne SPA: Shell bleibt, PJAX-Navigation, AJAX-Actions, serverseitige Wahrheit, deterministische Queues, konsistenter Planet Scope, kein State-Drift, neue Module brechen bestehende nicht.

Ab `v1.0.0-beta.1` gilt zusätzlich [BETA_GATE.md](BETA_GATE.md): Core Architecture Freeze. Neue Features erweitern bestehende Owner; Grundsysteme werden nicht mehr ersetzt.
