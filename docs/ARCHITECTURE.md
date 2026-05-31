# Genesis Colonies — Architecture

Technische Architektur-Dokumentation (Stand: **v1.5.3**). Ergänzt die [README](../README.md) mit Abläufen, Modulgrenzen und Datenflüssen.

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

---

## Design-Prinzipien

| Prinzip | Umsetzung |
|---------|----------|
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
│  templates/base.html     — Shell (nav, resource bar, planet switch)│
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
│  fleet*, galaxy, shipyard*, exchange, scrapyard                   │
│  planet_evolution/     — Multi-Kolonie, DNA, Planet-Forschung       │
│  chat, messages, alliance, support, ranking, playercard            │
│  auth, admin*, bootstrap, config, db, models                      │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ SQLite (WAL) — game/game.db                                       │
│  migration_history + migrations/*.sql (006–032)                   │
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

```
GET /api/game-state
  → @require_login
  → _build_game_state_payload()
       → refresh_player_live_state()
            → finish_due_work_once()     # queue_engine
            → update_planet_resources()  # context planet, skip_queue_finish
       → get_build_queue_status(skip_finish=True)
       → get_research_status(skip_finish=True)
       → exchange, fuel_exchange, scrapyard snapshots
  → JSON: resources, buildings, queues, active_planet, planets[], ...
```

Details: [STATE_AJAX.md](STATE_AJAX.md), [EFFECTS.md](EFFECTS.md).

Client (`static/main.js`): Singleton-Polling, `applyGameStateData()`, rAF-Ticker für Queues.

| Zustand | Intervall |
|---------|-----------|
| Aktive Queue | ~1000 ms |
| Idle | ~4000 ms |
| Tab hidden | ~12000 ms |
| Fehler | Exponential backoff bis 60 s |

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

Worker: `scripts/run_queue_tick.py`, Admin: `POST /api/admin/queue-tick`.

---

## Spielmodule (Status v1.5.3)

| Modul | Route(n) | Backend | Status |
|-------|----------|---------|--------|
| Overview | `/overview` | `overview_page.py` | ✅ |
| Buildings | `/buildings`, `/api/buildings/*` | `buildings.py` | ✅ |
| Research | `/research`, `/api/research/*` | `research.py` | ✅ |
| Tech tree | `/techtree` | `techtree.py` | ✅ |
| Trader Hub | `/trader-hub`, `/api/exchange`, `/api/trader/*` | `exchange.py`, `fuel_exchange.py`, `scrapyard.py` | ✅ |
| Shipyard | `/shipyard`, `/api/shipyard/*` | `shipyard.py`, `shipyard_queue.py` | ✅ |
| Galaxy | `/galaxy`, `/api/galaxy/system` | `galaxy.py` | ✅ |
| Fleet | `/fleet`, `/api/fleet/*` | `fleet.py`, `fleet_calc.py`, `fleet_defs.py` | ✅ (Combat placeholder) |
| Defense | `/defense` | — | 📋 UI only |
| Planet Evolution | `/planet-evolution`, `/api/planets/*` | `planet_evolution/` | ✅ |
| Ranking | `/ranking`, `/api/ranking` | `ranking.py` | ✅ |
| PlayerCard | `/player/<id>`, `/api/player-card/*` | `playercard.py` | ✅ |
| Messages | `/messages`, `/api/messages/*` | `messages.py`, `mail.py` | ✅ |
| Chat | partial in base, `/api/chat/*` | `chat.py` | ✅ |
| Alliance | `/alliance` | `alliance.py` | 🔄 Backend minimal, UI teils |
| Support | `/api/support/*` | `support.py` | ✅ |
| Options | `/options`, `/api/options/*` | `options.py` | ✅ |
| Admin | `/admin`, `/api/admin/*` | `admin.py`, `admin_api.py` | ✅ |

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

**Aktuelle Migrationen:** `006`–`032` (Scores → Fleet → Fuel → Exchange → Planet Evolution → Chat → Messages → Support → Galaxy → Fleet core → Colonize).

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

**513 pytest-Tests** (Stand v1.5.3), u. a.:

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
| Combat | EffectResolver prepared modifiers → neuer Resolver, **kein** paralleles Fleet-System |
| Neues Ticket | Max. 3–5 Dateien, Master-Doc aktualisieren wenn Architektur betroffen |

---

## Verwandte Dokumente

- [ROADMAP.md](ROADMAP.md) — Phasen & Meilensteine
- [README](../README.md) — Quick Start
- [LICENSE](../LICENSE) — Proprietär, kein Self-Hosting
- [SECURITY.md](SECURITY.md) — Threat Model
- [CONTRIBUTING.md](CONTRIBUTING.md) — Dev-Workflow
