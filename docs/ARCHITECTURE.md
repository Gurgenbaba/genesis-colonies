# Genesis Colonies — Architecture

Technische Architektur-Dokumentation (Stand: v1.5.1). Ergänzt die [README](../README.md) mit Abläufen, Modulgrenzen und Datenflüssen.

---

## Design-Prinzipien

| Prinzip | Umsetzung |
|---------|----------|
| **Server authority** | Spielzustand, Queues und Ressourcen werden ausschließlich serverseitig berechnet |
| **Conn-safe reads** | `_load_player_view_with_resources()` hält eine Connection für Tick + Finisher + Commit |
| **Write serialization** | SQLite: `BEGIN IMMEDIATE`; Postgres (geplant): `FOR UPDATE` Row-Locks |
| **Idempotent actions** | Client `request_id` → `action_idempotency` verhindert Double-Submit |
| **Thin HTTP layer** | `app.py` routet; Logik lebt in `game/*` |
| **No frontend build** | PJAX + Polling in Vanilla JS — deploybar wie eine klassische Flask-App |

---

## Systemübersicht

```
┌──────────────────────────────────────────────────────────────────┐
│ Client (Browser)                                                  │
│  templates/base.html  — persistent shell (nav, resource bar)      │
│  static/main.js       — GC namespace: PJAX, poll, actions, rAF   │
│  static/admin.js      — Admin Control Center (separate lifecycle)  │
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
│  logic ──► buildings, research, resources, ranking                 │
│  models ──► schema, users, idempotency, queue rows               │
│  db ──► connections, transactions, postgres hooks                │
│  auth, admin, admin_api, admin_audit, health, bootstrap, config    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│ SQLite (WAL) — game/game.db                                       │
│  migration_history + migrations/*.sql                             │
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
| `users` | Login (`username`, `password_hash`, `is_admin`) |
| `players` | Spielobjekt (`id` = `users.id`), Ban, `last_seen` |
| `planets` | Ressourcen, Energie, `player_id`, `is_homeworld` |
| `planet_buildings` | Spalten pro Gebäudetyp (Level) |
| `build_queue` | Bau-Jobs (`planet_id`, `finish_time`, `building_type`) |
| `research_queue` | Forschungs-Jobs (`user_id`, `finish_at`, `tech_key`) |
| `player_scores` | Gecachte Ranking-Punkte |
| `game_settings` | Universe-Config (Speed, MOTD, Queue-Limits) |
| `action_idempotency` | API-Replay-Cache (`user_id`, `request_id`) |
| `admin_audit_log` | Admin-Aktionen mit Payload |
| `migration_history` | Angewandte SQL-Migrationen |
| `bans` | Ban-Historie (optional, Anzeige-Grund) |

**Annahme:** `users.id == players.id` (1:1). Homeworld pro Spieler über `is_homeworld = 1`.

---

## Request-Flow: Ingame-Seite (SSR)

```
Browser GET /overview
    → @require_login (Session, Ban-Check, g.player)
    → _load_player_view_with_resources()
         → db() — eine Connection
         → update_resources() — Tick + due finishers
         → get_storage_capacity()
         → conn.commit()
    → render_template("overview.html", ...)
```

Legacy-Actions (`/upgrade/<type>`, `/research_start/<key>`) nutzen Redirect + Flash; die primäre UI nutzt JSON-APIs.

---

## Request-Flow: PJAX-Navigation

Client (`static/main.js`):

1. Klick auf `.gc-nav-link` (ohne `data-no-pjax`)
2. `GC.cleanupPage()` — rAF, intervals, AbortControllers, Polling stop
3. `fetch(url, { headers: { "X-PJAX": "true" } })`
4. Vollständiges HTML parsen → `#gc-main-content` (oder äquivalent) extrahieren
5. DOM ersetzen, `GC.initPage()` — Tabs, Actions, Polling neu starten

Admin (`/admin`) und externe Links sind mit `data-no-pjax="1` von PJAX ausgenommen.

```
  [Overview] ──PJAX──► [Buildings] ──PJAX──► [Research]
       │                    │                    │
       └────────────────────┴────────────────────┘
                    base.html shell bleibt
                    resource-bar + nav persistent
```

---

## Request-Flow: Singleton-Polling

```
GC.startPolling(active?)
    → setTimeout loop (nicht setInterval — verhindert Overlap)
    → refreshGameState("poll")
         → AbortController pro Request
         → GET /api/game-state
         → applyGameStateData() — DOM updates
         → startProgressTicker() — rAF zwischen Polls
```

| Zustand | Intervall |
|---------|-----------|
| Aktive Queue | ~1000 ms (`intervalActive`) |
| Idle | ~4000 ms (`intervalIdle`) |
| Tab hidden | ~12000 ms (`intervalHidden`) |
| Fehler | Exponential backoff bis 60 s |

**Auth-Safety:** Auf `/login`, `/register`, `/logout` und `data-auth-page="1"` wird kein Poll gestartet. Bei 401 wird Polling abgebrochen (`_authLoopAborted`).

**Server-Zeit:** Jede Antwort enthält `server_time` (Unix-Sekunden). Client interpoliert mit `performance.now()` für Countdowns.

---

## Request-Flow: Game Action (Upgrade / Research)

```
POST /api/buildings/upgrade
  Body: { building_type, request_id? }
    → get_idempotent_action() — Cache-Hit → sofortige JSON-Antwort
    → _load_player_view_with_resources()
    → queue_build() → queue_build_for_planet()
         BEGIN IMMEDIATE
         finish_due_build_jobs()
         Ressourcen prüfen + abbuchen
         Queue-Limit prüfen
         INSERT build_queue
         COMMIT
    → _action_json_response() — immer frischer state
    → save_idempotent_action() wenn request_id gesetzt
```

Antwort-Schema:

```json
{
  "ok": true,
  "reason": "queued",
  "job": { "...": "..." },
  "state": { "ok": true, "server_time": 1710000000, "resources": {}, "build_queue": {}, ... }
}
```

Fehler liefern ebenfalls `state` — UI kann ohne zweiten Fetch aktualisieren.

---

## Queue-Engine

### Bau-Queue (`game/buildings.py`)

1. **Due-Finisher** vor jeder Mutation (`finish_due_build_jobs`)
2. **Limit** aus `game_settings.queue_limit` (Default 3, min 1)
3. **Kosten** aus Level + Speed-Faktoren; atomisches `spend_planet_resources`
4. **Score** invalidieren nur wenn Jobs wirklich fertig wurden

### Forschungs-Queue (`game/research.py`)

- Eine aktive Forschung pro Spieler (Queue-Logik analog, `lock_player_for_update` für Postgres vorbereitet)
- `research_queue.start_at` (Migration 008) für präzise UI-Fortschritte

### Ressourcen-Tick (`game/resources.py` via `game/logic.py`)

- `update_resources()` berechnet Produktion seit `last_update`
- Energie-Ratio drosselt Minen-Produktion
- Storage-Caps begrenzen Metal/Crystal

---

## API-Referenz (Spieler)

| Route | Auth | Beschreibung |
|-------|------|--------------|
| `GET /api/status` | login | Spielzustand (Polling-Alias) |
| `GET /api/game-state` | login | Vollständiger Zustand inkl. `buildings_panel` |
| `POST /api/buildings/upgrade` | login | Gebäude queuen (idempotent) |
| `POST /api/research/start` | login | Forschung starten (idempotent) |
| `GET /health` | öffentlich | System-Health |

Header für Idempotenz: `X-Request-Id` oder JSON-Feld `request_id`.

---

## Admin Control Center

Zwei Schichten:

| Schicht | Dateien | Transport |
|---------|---------|-----------|
| **Legacy Forms** | `game/admin.py`, `/admin/*` POST | HTML Redirect + Flash |
| **Control Center** | `game/admin_api.py`, `static/admin.js` | JSON `/api/admin/*` |

Jede privilegierte API-Aktion ruft `audit()` → `admin_audit_log`.

Destruktive Operationen verlangen exakte Bestätigungsphrase im JSON-Body (`confirm`):

| Action Key | Phrase |
|------------|--------|
| `queue_clear` | `CLEAR QUEUE` |
| `planet_reset` | `RESET PLANET` |
| `remove_admin` | `REMOVE ADMIN` |
| `ban_player` | `BAN PLAYER` |
| `run_migrations` | `RUN MIGRATIONS` |

---

## Migrations-System

| Komponente | Rolle |
|------------|-------|
| `game/models.py` `init_db()` | Baseline-Schema (frische DB) |
| `migrations/*.sql` | Inkrementelle Änderungen |
| `migrate.py` | Runner: Statement-Split, idempotente Fehler, `migration_history` |
| `game/migrations_util.py` | Pending-Check für Bootstrap + Health |

Aktuelle Migrationen: `006`–`010` (Scores, Persistence, Legacy Planets, Admin Audit).

---

## Frontend-Module (`static/main.js`)

| Namespace / Objekt | Verantwortung |
|--------------------|---------------|
| `GC` | Globaler State, Lifecycle |
| `GC.polling` | Singleton poll loop |
| `GC.pageLifecycle` | rAF, timeouts, AbortControllers |
| `GC.cleanupPage()` | Navigation teardown |
| `GC.refreshGameState` | Zentraler Fetch |
| `GC.fetchGameAction` | POST mit `request_id` |
| PJAX-Handler | Shell-preserving navigation |
| Progress ticker | rAF-basierte Queue-Balken |

Admin-JS ist bewusst getrennt — kein PJAX, eigenes Fetch-Layer (`adminGet` / `adminPost`).

---

## Postgres-Vorbereitung

`game/db.py` reserviert:

- `GC_DB_BACKEND=postgres` (aktuell: `NotImplementedError`)
- `lock_planet_for_update()` / `lock_player_for_update()` — No-Op auf SQLite, `FOR UPDATE` auf Postgres
- Portable SQL in Migrationen wo möglich

---

## Erweiterungspunkte (neue Features)

| Feature | Empfohlener Einstieg |
|---------|---------------------|
| Neues Gebäude | `BUILDING_KEYS`, `planet_buildings`-Spalte, `BASE_COST`, Template-Zeilen |
| Neue Tech | `game/research.py` Tech-Definitionen, Tech-Tree in `game/techtree.py` |
| Galaxie / Flotte | Neues `game/galaxy.py`, Routen in `app.py`, PJAX-Template |
| Echtzeit-Events | Optional WebSocket-Schicht — Polling bleibt Fallback |

Neue Schema-Änderungen **immer** als `migrations/NNN_name.sql` + Test in `test_persistence.py`.

---

## Verwandte Dokumente

- [README](../README.md) — Übersicht & Quick Start
- [DEPLOYMENT.md](DEPLOYMENT.md) — Production Setup
- [SECURITY.md](SECURITY.md) — Threat Model & Hardening
- [CONTRIBUTING.md](CONTRIBUTING.md) — Dev-Workflow
- [ROADMAP.md](ROADMAP.md) — Geplante Meilensteine
