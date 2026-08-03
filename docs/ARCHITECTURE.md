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
| [BETA_GATE.md](BETA_GATE.md) | Alpha-Exit, Core Architecture Freeze, Beta-Governance |
| [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) | Navigation, Actions, Lifecycle |
| [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) | Queue Finish / Cancel / Reschedule |
| [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | Planet Defense, Queue, Ranking |
| [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | Battle resolver, loot, debris, reports |
| [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) | Code-Reality-Status aller Module |
| [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md) | Economy-Ankerkurven (Code-generiert) |

**Golden Rule:** Genesis Colonies bevorzugt **Konsistenz über Komfort** — keine parallelen Systeme, keine Duplicate-Math, keine Reload-Navigation. Siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) (Regeln 15–17).

**Beta Governance:** Der Übergang zu `v1.0.0-beta.1` und der anschließende Core Architecture Freeze sind in [BETA_GATE.md](BETA_GATE.md) verbindlich geregelt.

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
│  migration_history + migrations/*.sql (006–124)                   │
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
Header (Brand, HUD, Account) — kein Planet-Switcher
├─ Resource Bar (sticky)
├─ .gc-layout--dual  (max-width: --gc-shell-max-width, default 1360px)
│   ├─ Left Sidebar — Gameplay   (#gc-sidebar-nav, sidebar.html)
│   │     Kommando · Infrastruktur · Militär
│   ├─ Main Content              (#main-content)
│   └─ Right rails (.gc-sidebar-right-rails, display:contents on desktop)
│         Meta (#gc-sidebar-nav-right) · Planet Registry (#gc-planet-registry)
└─ Bottom Utility Dock           (bottom_utility_bar.html)
      Support · Tickets · Impressum · Regeln · Discord · Wiki · Tchat · Version
```

| Partial | Rolle |
|---------|--------|
| `templates/partials/sidebar.html` | Linke Gameplay-Navigation |
| `templates/partials/planet_registry.html` | Rechte Imperiumsübersicht / Planet-Wechsel (GC-575) |
| `templates/partials/sidebar_right.html` | Rechte Rail: Registry + Meta compact |
| `templates/partials/bottom_utility_bar.html` | Utility-Links + Versions-Chip |
| `templates/partials/special_panel.html` | Support/Wiki/Tchat-Fenster (vom Dock geöffnet) |

**Responsive:**

| Viewport | Verhalten |
|----------|-----------|
| Desktop ≥1280px | Beide Sidebars + Registry immer sichtbar — **kein Wide-Mode**; Shell zentriert (`--gc-shell-max-width`) |
| Tablet 992–1279px | Rechte Sidebar als Drawer (Meta-Toggle im Bottom Dock) |
| Mobile <768px | Bottom Dock aus; bestehende Bottom-Nav + Drawer unverändert |

**Client-UI-State (kein Game-State):** Accordion-Sektionen in `localStorage` (`gc_sidebar_state`, `gc_sidebar_right_state`, `gc_planet_registry_meta_open`); Role-Sync aus `active_planet.sidebar_nav` via `GC.syncRoleBasedSidebar()`.

**Content-Regel:** Breite Seiten (Fleet, Galaxy, Ranking, Buildings) scrollen **intern** (`min-width: 0`, Tabellen-/Card-Wrapper). Navigation wird auf Desktop nicht ausgeblendet, um Breite zu gewinnen — siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §3. Rechte Rail: `--gc-registry-rail-w` (Planet Registry + Meta compact).

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
| Fleet tick | global (`game/fleet_worker.py` → `process_fleet_tick(player_id=None)`); per-player on live refresh |

Request-Dedup via Flask `g` + `live_state.coerce_skip_finish()`.

**Kanonische Timer-Anzeige:** Aktiver Job → Rest bis `finish_at`. Wartende Jobs → `finish_at − now` (Summe aller Vorgänger + eigene Dauer). Unit-Queues (Werft, Verteidigung): Auftrag = `ceil(amount / capacity) × unit_seconds` (Batch) — Details [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md).

Worker: `scripts/run_queue_tick.py`, Admin: `POST /api/admin/queue-tick`.

**Ranking batch (scores + ranks, 10 min):** `game/ranking_worker.run_ranking_worker()` — gameplay marks `player_score_dirty` only (`score_events`); ordinary worker runs refresh dirty players (GC-SCORE-PERF-001). Admin / daily safety-net: full reconcile. Admin: `POST /api/admin/ranking/recompute`.

**Railway SQLite:** maintenance runs **inside the web process** (embedded cron, default in production) on the same `/data/game.db` volume — not a separate worker service. Operator checklist: [RAILWAY_OPERATOR.md](RAILWAY_OPERATOR.md).

Optional manual/force HTTP cron (same bag):

```text
POST /api/internal/cron/ranking
Authorization: Bearer $GC_INTERNAL_CRON_TOKEN
```

Optional `?force=1` bypasses the 10-minute interval guard. Local manual runs: `scripts/run_ranking_worker.py` (deprecated on Railway SQLite).

**Vote Center admin stats:** `game/vote_rewards.build_admin_vote_stats()` / `search_admin_vote_players()` — reports **external verified votes** vs **historical synthetic grants** (`vote_channel=reengagement`). Synthetic re-engagement grants are fully removed (no cron, admin, CLI, or env kill-switch). Historical rows remain for reporting and do **not** drive provider cooldowns.

**Fleet tick (global, ~60 s idle guard):** `game/fleet_worker.run_fleet_worker()` — processes due `fleet_movements` for **all** players while offline. Piggybacks on ranking HTTP cron; dedicated: `POST /api/internal/cron/fleet-tick` (same bearer token). Live requests also run a throttled global safety net in `_load_page_live_context`. Env: `GC_FLEET_WORKER_INTERVAL_SEC` (default 60).


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
| Alliance | `/alliance`, `/api/alliance/*` | `alliance.py`, `alliance_catalog.py` | ✅ MVP complete (GC-AL-MVP-09) |

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
| `POST /api/alliance/*` | login | Allianz-Actions → `{ ok, state, alliance }` |
| `GET /health` | öffentlich | System-Health |

Vollständige Routenliste: `app.py` (grep `@app.route`).

Header für Idempotenz: `X-Request-Id` oder JSON-Feld `request_id`.

---

## Admin Control Center

Owner doc: [ADMIN_CONTROL_CENTER.md](ADMIN_CONTROL_CENTER.md).

| Schicht | Dateien | Transport |
|---------|---------|-----------|
| **Control Center** | `templates/admin_panel.html`, `static/admin.js`, `static/admin.css`, `game/admin_api.py` | Hard-load `/admin` + JSON `/api/admin/*` |
| **Legacy HTML POST** | `/admin/update|resources|wipe|ban|unban` | **Deprecated stubs** (flash + redirect, no mutation) |

Grouped nav (LiveOps / Players / Economy / Moderation / System). Assets load only on `/admin`.

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

**Aktuelle Migrationen:** `006`–`123` — siehe `migrations/` und `migration_history`.

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

## Request Performance Trace (GC-PERF-REQUEST-TRACE)

Abschaltbares Server-Logging für **langsame HTTP-Requests** — ergänzt `GC_PERF_DEBUG` (Actions) und `GC_SSR_PERF_DEBUG` (SSR-Seiten), ersetzt sie nicht.

### Flags

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `GC_REQUEST_PERF_DEBUG` | `0` | `1` = Request-Trace aktiv |
| `GC_PERF_DEBUG` | `0` | Aktiviert implizit auch Request-Trace (konsistent mit GC-841) |
| `GC_REQUEST_PERF_SLOW_MS` | `500` | Nur Requests mit `total_ms` ≥ Schwellwert loggen |
| `GC_REQUEST_PERF_SAMPLE` | `1.0` | Anteil gemessener Requests (`0.0`–`1.0`) |

### Production-Empfehlung (Railway)

```env
GC_REQUEST_PERF_DEBUG=1
GC_REQUEST_PERF_SLOW_MS=500
GC_REQUEST_PERF_SAMPLE=1.0
```

30–60 Minuten unter echter Last, dann bei zu hohem Logvolumen `GC_REQUEST_PERF_SAMPLE=0.1`.

### Logformat

Eine Zeile pro langsamem Request:

```text
[GC REQUEST PERF] method=GET endpoint=api_game_state path=/api/game-state status=200 total_ms=842.4 bytes=28400 sample=1 finish_source=game_state_panel include_panel=1 fleet_tick_ms=45.2 finish_ms=620.0 resource_sync_ms=180.4 payload_ms=31.8 sql_count=47 db_begin_immediate_ms=12.3 db_write_transaction_ms=602.0
```

### Phasen (Owner: `game/live_state.py`)

| Phase | Owner | Bedeutung |
|-------|-------|-----------|
| `fleet_tick_ms` | `app.py` before_request | Globaler Fleet-Tick inkl. Lock-Wartezeit |
| `live_context_ms` | `_build_game_state_payload` | Live-Context-Laden |
| `finish_ms` | `refresh_player_live_state` / poll path | Queue-Finish |
| `resource_sync_ms` | `logic.py` | Ressourcen-Sync |
| `payload_ms` | `_build_game_state_payload` | State-Payload-Aufbau |
| `db_begin_immediate_ms` | `game/db.py` | `BEGIN IMMEDIATE` inkl. SQLite-Lock-Wait |
| `db_write_transaction_ms` | `game/db.py` | Write-TX von Begin bis Commit/Rollback |

Action-/SSR-Phasen werden beim Log aus bestehenden `ActionPerfTrace` / `SsrPerfTrace` übernommen (keine Doppelberechnung).

### Datenschutz

Keine Spielernamen, Session-IDs, Request-Bodies, Tokens oder SQL-Parameter. Routing über `request.endpoint`; `path` nur ergänzend.

### Bekannte Grenzen

- **Keine zuverlässige Einzel-SQL-Dauer** — `set_trace_callback` zählt nur (`sql_count` / `sql_write_count`), misst keine Statement-Laufzeit.
- **Keine prozessübergreifende p95-Aggregation** — Auswertung aus strukturierten Logs (Railway Log Search).
- **Keine Prometheus-Persistenz** in diesem Ticket.

### GC-PERF-CORE-001 — Budgets

Harte Zielwerte in `game.config.get_perf_budgets()` (siehe [GC_PERF_CORE.md](GC_PERF_CORE.md)).
Bei aktivem Request-Trace und Überschreitung: Meta-Feld `budget_miss=diet_poll_ms,…`.
Diet-Payload-Größe: `diet_payload_bytes` nach `apply_lightweight_game_state_diet`.
Baseline: `python scripts/perf_baseline.py`.

---

## Postgres-Vorbereitung / GC-PERF-DB-002

`game/db.py` + Adapter `game/db_pg.py`:

- `GC_DB_BACKEND=postgres` + `DATABASE_URL=postgresql://…`
- Connection Pool (`psycopg_pool`, `GC_PG_POOL_MAX`)
- `?` → `%s` Placeholder-Rewrite
- `lock_planet_for_update()` / `lock_player_for_update()` — `FOR UPDATE`
- Portable `table_exists` / `table_columns` / `index_exists`
- SQLite bleibt Default für Dev und bestehende Deploys

Audit: [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md) · Epic: [GC_PERF_CORE.md](GC_PERF_CORE.md)

---

## Test-Suite

**4219 pytest-Tests** (Stand v0.5.9.87 — `python -m pytest --collect-only -q`), u. a.:

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
- [BETA_GATE.md](BETA_GATE.md) — Alpha-Exit und Core Architecture Freeze
- [README](../README.md) — Quick Start
- [LICENSE](../LICENSE) — Proprietär, kein Self-Hosting
- [SECURITY.md](SECURITY.md) — Threat Model
- [CONTRIBUTING.md](CONTRIBUTING.md) — Dev-Workflow
