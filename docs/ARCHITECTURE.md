# Genesis Colonies — Architecture

Technische Architektur-Dokumentation (Stand: **v1.5.9.2**, Reality-Sync **2026-06-24**). Ergänzt die [README](../README.md) mit Abläufen, Modulgrenzen und Datenflüssen.

**System-Docs (Single Source of Truth pro Domäne):**

| Dokument | Domäne |
|----------|--------|
| [WORKFLOW.md](WORKFLOW.md) | Ticket-Workflow, Einstieg |
| [PLANET_SCOPE.md](PLANET_SCOPE.md) | Aktiver Planet, Multi-Kolonie |
| [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) | DNA, Planet-Tech, Events |
| [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) | Ressourcen, Exchange, Trader Hub |
| [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) | Gebäude, Bau-Queue |
| [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) | Account-Forschung |
| [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | Flotten, Schiffe, Missionen |
| [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) | Koordinaten, Systemansicht |
| [EFFECTS.md](EFFECTS.md) | EffectResolver, Formeln |
| [STATE_AJAX.md](STATE_AJAX.md) | Live-Polling, PJAX |
| [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) | GC-000 — verbindliche Kernregeln |
| [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) | Navigation, Actions, Lifecycle |
| [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) | Queue Finish / Cancel / Reschedule |
| [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | Planet Defense, Queue, Ranking |
| [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | Battle resolver, loot, debris, reports |
| [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) | Code-Reality-Status aller Module |
| [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md) | Economy-Ankerkurven (Code-generiert) |

**Golden Rule:** Genesis Colonies bevorzugt **Konsistenz über Komfort** — keine parallelen Systeme, keine Duplicate-Math, keine Reload-Navigation. Siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) (Regeln 15–17).

---

## Design-Prinzipien

| Prinzip | Umsetzung |
|---------|----------|
| **Consistency over comfort** | Bestehendes kanonisches System erweitern, nicht duplizieren ([CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §15–17) |
| **Server authority** | Spielzustand, Queues, Ressourcen und Flotten werden serverseitig berechnet |
| **Planet scope** | UI und Ressourcen-Actions nutzen `get_context_planet()` — aktiver Planet in `players.active_planet_id` |
| **Conn-safe reads** | `_load_page_live_context()` hält eine Connection für Tick + Finisher + Commit |
| **Single finish pass** | `refresh_player_live_state()` + `coerce_skip_finish()` verhindern doppeltes Queue-Finish pro Request |
| **Write serialization** | SQLite: `BEGIN IMMEDIATE`; Postgres (geplant): `FOR UPDATE` Row-Locks |
| **Idempotent actions** | Client `request_id` → `action_idempotency` verhindert Double-Submit |
| **Thin HTTP layer** | `app.py` routet; Logik lebt in `game/*` |
| **No frontend build** | PJAX + Polling in Vanilla JS — deploybar wie eine klassische Flask-App |
| **Kanonische Systeme** | Keine parallelen Implementierungen (z. B. `orbital_shipyard`, nicht `shipyard` + Duplikat) |

---

## Systemübersicht

```
┌──────────────────────────────────────────────────────────────────┐
│ Client (Browser)                                                  │
│  templates/base.html     — Shell (dual sidebars, header, bottom dock)│
│  static/main.js          — GC: PJAX, poll, actions, fleet, scope  │
│  static/js/chat.js       — Genesis TChat (eigenes Polling)        │
│  static/js/messages.js   — Inbox                                  │
│  static/admin.js         — Admin Control Center                   │
└────────────────────────────┬─────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │ HTML (Jinja2)     │ JSON APIs         │
         ▼                   ▼                   ▼
┌──────────────────────────────────────────────────────────────────┐
│ app.py — Flask                                                    │
│  @require_login / @require_admin / @require_admin_api             │
│  bootstrap_application() at import time                           │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ game/ — Domain + Infrastructure                                   │
│  logic, live_state     — Poll-Pipeline, Action-Responses          │
│  resources, buildings, research, effects/                         │
│  queue_engine          — Zentraler Due-Finisher (Build/Research/  │
│                          Shipyard/Fleet/Planet-Evolution)         │
│  fleet*, galaxy, shipyard*, defense*, combat*, exchange, scrapyard │
│  planet_evolution/     — Multi-Kolonie, DNA, Planet-Forschung       │
│  chat, messages, alliance, support, ranking, playercard            │
│  auth, admin*, bootstrap, config, db, models                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ SQLite (WAL) — game/game.db                                       │
│  migration_history + migrations/*.sql (006–076)                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Prozess-Start (Bootstrap)

Beim Import von `app.py`:

```
1. init_config()           — .env laden, DATABASE_URL → GC_DB_PATH
2. validate_config()       — Production: SECRET_KEY, FLASK_DEBUG
3. init_db()               — CREATE TABLE IF NOT EXISTS (Baseline-Schema)
4. purge_stale_idempotency_global()
5. migrations_are_current() — Production: Exit wenn pending
6. app.secret_key = get_secret_key()
```

`GC_SKIP_MIGRATION_CHECK=1` überspringt Schritt 5 (nur Tests/CI).

Installer (`scripts/install.py`) führt Bootstrap + `migrate.py` in isolierter Umgebung aus.

---

## Datenmodell (Kern)

| Tabelle | Rolle |
|---------|-------|
| `users` | Login, E-Mail, Passwort-Hash, Verifikation |
| `players` | Spielobjekt (`id` = `users.id`), Ban, `last_seen`, `active_planet_id`, Exchange-Tageslimit |
| `planets` | Ressourcen (metal, crystal, fuel_cells), Energie, Koordinaten, Evolution-Felder |
| `planet_buildings` | Spalten pro Gebäudetyp (Level) pro Planet |
| `build_queue` | Bau-Jobs (`planet_id`, `finish_time`, `building_type`) |
| `research_levels` / `research_queue` | Account-weite Tech-Levels und Queue |
| `shipyard_queue` | Schiffsbau pro Planet |
| `planet_ships` | Schiffsbestand pro Planet |
| `fleet_movements` / `fleet_presets` / `fleet_batches` | Flottenlogik |
| `planet_dna`, `planet_*` (Evolution) | Planet Evolution Subsystem — siehe Migration 016–018 |
| `player_scores` | Gecachte Ranking-Punkte |
| `exchange_log` | Trader-Hub Metall↔Kristall |
| `chat_*`, `player_messages`, `support_tickets` | Social / Support |
| `alliances` / `alliance_members` | Allianz (Basis für Chat + Fleet hold) |
| `game_settings` | Universe-Config (Speed, MOTD, Queue-Limits, Galaxy-Count) |
| `action_idempotency` | API-Replay-Cache |
| `admin_audit_log` | Admin-Aktionen |
| `migration_history` | Angewandte SQL-Migrationen |

**Annahmen:** `users.id == players.id` (1:1). Homeworld pro Spieler über `is_homeworld = 1`. Koordinaten unique pro Slot (Migration 026).

---

## Request-Flow: Live State (Polling)

Zwei Pfade — Details: [STATE_AJAX.md](STATE_AJAX.md).

**Diet poll** (`GET /api/game-state`, ohne `include_panel`):

```
→ read_player_live_state_for_poll()  # leichtgewichtig
→ finish_source=game_state
→ HUD-only patch (Ressourcen, Queues-Zähler, keine vollen Panels)
```

**Full refresh** (Page load, Actions, Timer-Zero, `include_panel=1`):

```
→ refresh_player_live_state()
     → finish_due_work_once()
     → update_planet_resources(skip_queue_finish=True)
→ get_build_queue_status(skip_finish=True) / get_research_status(skip_finish=True)
→ panels: buildings, defense, shipyard, exchange, …
```

Orchestrierung: `app.py` (`_build_game_state_payload`, `_load_page_live_context`) + `game/logic.py` + `game/live_state.py`.

Client (`static/main.js`): Singleton-Polling, `applyGameStateData()`, `applyActionState()`, rAF-Ticker für Queues.

**Poll-Intervalle:** siehe [STATE_AJAX.md](STATE_AJAX.md) und `game/config.py` `get_client_runtime_config()` (Production: 8 / 12 / 30 s).

---

## Navigation Shell (GC-806)

Seit **GC-804–806C** nutzt die Ingame-Shell in `templates/base.html` ein festes **Dual-Sidebar-Layout** plus **Bottom Utility Dock**. PJAX ersetzt weiterhin nur `#main-content`; Sidebars und Dock bleiben in der Shell erhalten ([AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)).

```
Header (Brand, HUD, Planet Switcher, Account)
├─ Resource Bar (sticky)
├─ .gc-layout--dual  (max-width: --gc-shell-max-width, default 1360px)
│   ├─ Left Sidebar — Gameplay   (#gc-sidebar-nav, sidebar.html)
│   │     Kommando · Infrastruktur · Militär
│   ├─ Main Content              (#main-content)
│   └─ Right Sidebar — Meta      (#gc-sidebar-nav-right, sidebar_right.html)
│         Nachrichten · Wirtschaft · Community · System
└─ Bottom Utility Dock           (bottom_utility_bar.html)
      Support · Tickets · Impressum · Regeln · Discord · Wiki · Tchat · Version
```

| Partial | Rolle |
|---------|--------|
| `templates/partials/sidebar.html` | Linke Gameplay-Navigation |
| `templates/partials/sidebar_right.html` | Rechte Meta-/Community-Navigation |
| `templates/partials/bottom_utility_bar.html` | Utility-Links + Versions-Chip |
| `templates/partials/special_panel.html` | Support/Wiki/Tchat-Fenster (vom Dock geöffnet) |

**Responsive:**

| Viewport | Verhalten |
|----------|-----------|
| Desktop ≥1280px | Beide Sidebars immer sichtbar — **kein Wide-Mode** |
| Tablet 992–1279px | Rechte Sidebar als Drawer (Meta-Toggle im Bottom Dock) |
| Mobile <768px | Bottom Dock aus; bestehende Bottom-Nav + Drawer unverändert |

**Client-UI-State (kein Game-State):** Accordion-Sektionen in `localStorage` (`gc_sidebar_state`, `gc_sidebar_right_state`); Role-Sync aus `active_planet.sidebar_nav` via `GC.syncRoleBasedSidebar()`.

**Content-Regel:** Breite Seiten (Fleet, Galaxy, Ranking, Buildings) scrollen **intern** (`min-width: 0`, Tabellen-/Card-Wrapper). Navigation wird auf Desktop nicht ausgeblendet, um Breite zu gewinnen — siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §3.

---

## Request-Flow: PJAX-Navigation

1. Klick auf `.gc-nav-link` (ohne `data-no-pjax`)
2. `GC.cleanupPage()` — rAF, intervals, AbortControllers, Polling stop
3. `fetch(url, { headers: { "X-PJAX": "true" } })`
4. HTML parsen → `#main-content` extrahieren
5. DOM ersetzen, `GC.initPage()` — Module (fleet, galaxy, …) neu starten

**Planet scope:** Nach Planetwechsel `POST /api/planets/active` → `reloadCurrentPage()`; scoped Pages (fleet, shipyard, trader-hub) reloaden bei `active_planet_id` ≠ DOM `data-planet-id`.

Details: [PLANET_SCOPE.md](PLANET_SCOPE.md).

---

## Queue-Engine (`game/queue_engine.py`)

Zentraler Due-Finisher für:

| Typ | Scope |
|-----|-------|
| Build | pro Planet |
| Account research | pro Spieler |
| Planet research / ascension | pro Planet (Evolution) |
| Shipyard | pro Planet |
| Fleet tick | pro Spieler (`process_fleet_tick`) |

Request-Dedup via Flask `g` + `live_state.coerce_skip_finish()`.

**Kanonische Timer-Anzeige:** Aktiver Job → Rest bis `finish_at`. Wartende Jobs → `finish_at − now` (Summe aller Vorgänger + eigene Dauer). Unit-Queues (Werft, Verteidigung): Auftrag = `amount × unit_build_time`, seriell — Details [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md).

Worker: `scripts/run_queue_tick.py`, Admin: `POST /api/admin/queue-tick`.

---

## Spielmodule (Status v1.5.9.2)

Vollständige Tabelle: **[PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)** — hier nur Kernmodule:

| Modul | Route(n) | Backend | Status |
|-------|----------|---------|--------|
| Overview | `/overview` | `overview_page.py` | ✅ |
| Buildings | `/buildings`, `/api/buildings/*` | `buildings.py` | ✅ |
| Research | `/research`, `/api/research/*` | `research.py` | ✅ |
| Trader Hub | `/trader-hub`, `/api/exchange`, … | `exchange.py`, `scrapyard.py` | ✅ |
| Shipyard | `/shipyard`, `/api/shipyard/*` | `shipyard.py` | ✅ ⚠️ GC-512D envelope |
| Defense | `/defense`, `/api/defense/*` | `defense.py` | ✅ |
| Fleet / Combat | `/fleet`, `/api/fleet/*` | `fleet.py`, `combat.py` | ✅ |
| Galaxy | `/galaxy` | `galaxy.py` | ✅ |
| Empire / Command Map | `/empire`, `/api/command-map/*` | `planet_evolution/command_map.py` | ✅ |
| Planet Evolution | `/planet-evolution` | `planet_evolution/` | ✅ |
| Inventory / Auction / Vote | `/inventory`, `/auction-house`, `/vote-center` | respective modules | ✅ |
| Alliance | `/alliance` | `alliance.py` | 🔄 Backend minimal |

---

## API-Referenz (Auszug)

| Route | Auth | Beschreibung |
|-------|------|--------------|
| `GET /api/game-state` | login | Kanonischer Poll-Payload |
| `GET /api/status` | login | Alias von game-state |
| `POST /api/buildings/upgrade` | login | Gebäude queuen (idempotent) |
| `POST /api/research/start` | login | Forschung starten (idempotent) |
| `POST /api/planets/active` | login | Aktiven Planet setzen |
| `GET /api/fleet/state` | login | Flotten-Live-State + Tick |
| `POST /api/fleet/send` | login | Flotte senden |
| `GET /api/galaxy/system` | login | System-Slots JSON |
| `GET /health` | öffentlich | System-Health |

Vollständige Routenliste: `app.py` (grep `@app.route`).

Header für Idempotenz: `X-Request-Id` oder JSON-Feld `request_id`.

---

## Admin Control Center

| Schicht | Dateien | Transport |
|---------|---------|-----------|
| **Legacy Forms** | `game/admin.py`, `/admin/*` POST | HTML Redirect + Flash |
| **Control Center** | `game/admin_api.py`, `static/admin.js` | JSON `/api/admin/*` |

Jede privilegierte API-Aktion ruft `audit()` → `admin_audit_log`.

Balance-Editor: `game/admin_balance.py` → `/api/admin/balance`.

---

## Migrations-System

| Komponente | Rolle |
|------------|-------|
| `game/models.py` `init_db()` | Baseline-Schema (frische DB) |
| `migrations/*.sql` | Inkrementelle Änderungen |
| `migrate.py` | Runner, `migration_history` |
| `game/migrations_util.py` | Pending-Check für Bootstrap + Health |

**Aktuelle Migrationen:** `006`–`076` — siehe `migrations/` und `migration_history`.

Neue Schema-Änderungen **immer** als `migrations/NNN_name.sql` + Test in `test_persistence.py`.

---

## Frontend-Module (`static/main.js`)

| Namespace / Objekt | Verantwortung |
|--------------------|---------------|
| `GC` | Globaler State, Lifecycle |
| `GC.polling` | Singleton poll loop |
| `GC.pageLifecycle` | rAF, timeouts, AbortControllers |
| `GC.modules.*` | Page init: fleet, galaxy, shipyard, … |
| `GC.cleanupPage()` | Navigation teardown |
| `GC.refreshGameState` | Zentraler Fetch |
| `GC.reloadCurrentPage` | PJAX reload bei Planetwechsel |
| PJAX-Handler | Shell-preserving navigation |

Chat (`static/js/chat.js`) und Messages (`static/js/messages.js`) haben eigenes Polling; Chat wird nach PJAX via `GC.resumeChatPolling()` fortgesetzt.

---

## Postgres-Vorbereitung

`game/db.py` reserviert:

- `GC_DB_BACKEND=postgres` (aktuell: `NotImplementedError`)
- `lock_planet_for_update()` / `lock_player_for_update()` — No-Op auf SQLite
- Portable SQL in Migrationen wo möglich

---

## Test-Suite

**2183 pytest-Tests** (Stand v1.5.9.2 — `python -m pytest --collect-only -q`), u. a.:

- `test_persistence.py`, `test_race_conditions.py` — DB/Queues
- `test_game_state_live.py`, `test_effects.py`, `test_queue_engine.py` — Live pipeline
- `test_fleet.py`, `test_galaxy.py`, `test_shipyard*.py` — Military
- `test_planet_instancing.py`, `test_planet_evolution*.py` — Multi-Kolonie
- `test_chat.py`, `test_messages.py`, `test_trader_hub.py` — Meta

```bash
python -m pytest -q
```

---

## Erweiterungspunkte

| Feature | Einstieg |
|---------|----------|
| Neues Gebäude | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md), Migration, `EffectResolver` |
| Neue Tech | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md), `techtree.py` |
| Neues Schiff / Mission | [FLEET_SYSTEM.md](FLEET_SYSTEM.md), `fleet_defs.py` |
| Combat | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) — `simulate_battle()`; **kein** paralleles Fleet-System |
| Neues Ticket | Max. 3–5 Dateien, Master-Doc aktualisieren wenn Architektur betroffen |

---

## Verwandte Dokumente

- [ROADMAP.md](ROADMAP.md) — Phasen & Meilensteine
- [README](../README.md) — Quick Start
- [LICENSE](../LICENSE) — Proprietär, kein Self-Hosting
- [SECURITY.md](SECURITY.md) — Threat Model
- [CONTRIBUTING.md](CONTRIBUTING.md) — Dev-Workflow
