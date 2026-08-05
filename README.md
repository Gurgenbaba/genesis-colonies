# Genesis Colonies

**Build. Research. Command the cluster.**

Browser-basiertes Sci-Fi-Strategiespiel (OGame-inspiriert) — entwickelt als production-ready Web-App mit Flask, SQLite und einer SPA/PJAX-Frontend-Schicht ohne Build-Toolchain.

| | |
|---|---|
| **Version** | `0.5.9.104` (siehe [`VERSION`](VERSION)) · Spieler-Meilenstein **v0.9 Alpha** |
| **Stack** | Python 3.10+ · Flask 3 · SQLite (WAL) · Vanilla JS |
| **Status** | Alpha (`v0.9`) — Economy, Combat, Defense, Fleet, Alliance MVP, Imperium spielbar · Beta/`v1.0` erst nach [BETA_GATE.md](docs/BETA_GATE.md) |
| **Health** | `GET /health` |

---

## Projektübersicht

Genesis Colonies ist ein persistentes Browser-Strategiespiel, in dem Spieler eine Kolonie aufbauen, Ressourcen produzieren, Gebäude erweitern und Technologien erforschen. Das Backend liefert serverseitige Spielmechanik; das Frontend aktualisiert Ressourcen, Queues und UI-Zustände in Echtzeit — ohne Full-Page-Reloads.

**Ziel:** Ein ernsthaft entwickeltes Browser-Strategiespiel mit klarer Architektur und operativen Werkzeugen für Admins.

**Vision:** Von der spielbaren Wirtschaftskern-Phase zu Galaxie, Flotten, Allianzen und Multiplayer-Systemen — auf einer Basis, die Race Conditions, Idempotenz und Migrationen von Anfang an berücksichtigt.

**Hosting:** Genesis Colonies wird ausschließlich vom Projekt betrieben. Siehe [LICENSE](LICENSE).

---

## Aktueller Status

### Stabil / produktionsreif (Infrastruktur)

| Bereich | Stand |
|---------|-------|
| Installer & Bootstrap | `scripts/install.py`, Migration Guard |
| Health Monitoring | `GET /health` mit DB-, Migrations-, Config- und Write-Checks |
| DB-Migrationen | Versioniertes SQL-System (`migrations/`, `migrate.py`) |
| Admin Control Center | JSON-API + operatives UI (`/admin`, `/api/admin/*`) |
| Audit Logging | `admin_audit_log` für privilegierte Aktionen |
| Frontend-Architektur | SPA/PJAX, Singleton-Polling, Lifecycle-Cleanup |
| Queue-Hardening | Atomare Transaktionen, Idempotenz, Parallel-Tests |
| Test-Suite | **4437** pytest-Tests (`python -m pytest --collect-only -q`) |

### Spielbar (Mechanik)

| Modul | Route | Status |
|-------|-------|--------|
| Landing | `/` | ✅ |
| Auth (+ E-Mail, Passwort-Reset) | `/register`, `/login`, … | ✅ |
| Übersicht | `/overview` | ✅ Live-Ressourcen, Queues, Fleet-Aktivität |
| Gebäude | `/buildings` | ✅ Bauen, Upgrade, Queue |
| Forschung (Account) | `/research` | ✅ Techs, Queue |
| Tech-Tree | `/techtree` | ✅ |
| Trader Hub | `/trader-hub` | ✅ Exchange, Brennzellen, Schrottplatz |
| Werft | `/shipyard` | ✅ Schiffsbau-Queue |
| Verteidigung | `/defense` | ✅ Bau-Queue, Ranking |
| Galaxie | `/galaxy` | ✅ Koordinaten, Slots, Expedition |
| Flotte | `/fleet` | ✅ Send, Tick, Combat, Recycler, Logistics |
| Imperium / Command Map | `/empire` | ✅ World Map MVP |
| Inventar | `/inventory` | ✅ Container, Loot |
| Auktionshaus | `/auction-house` | ✅ |
| Vote Center | `/vote-center` | ✅ |
| Planet Evolution | `/planet-evolution` | ✅ DNA, Planet-Tech, Events |
| Ranking | `/ranking` | ✅ |
| Messages | `/messages` | ✅ |
| Chat | Header-Widget | ✅ |
| PlayerCard | `/player/<id>` | ✅ |
| Allianz | `/alliance` | ✅ MVP (Hub, Spenden, Projekte, Tech, Boni) |
| Options | `/options` | ✅ |
| Admin | `/admin` | ✅ Control Center |

### Tech debt / Placeholder

| Modul | Route | Status |
|-------|-------|--------|
| Shipyard API envelope | `/api/shipyard*` | ⚠️ `{ok,data}` statt `{ok,state}` (GC-512D) |

Vollständiger Modul-Status: [docs/PROJECT_INVENTORY.md](docs/PROJECT_INVENTORY.md) · Capability-Überblick: [docs/CAPABILITY_STATUS.md](docs/CAPABILITY_STATUS.md) · Balance-Anker: [docs/BALANCE_ANCHORS.md](docs/BALANCE_ANCHORS.md)

---

## Kernfeatures

### SPA/PJAX ohne Framework

Navigation zwischen Ingame-Seiten erfolgt per PJAX (`X-PJAX: true`): Flask liefert HTML-Fragmente, `static/main.js` tauscht den Content-Bereich aus. Kein Node.js, kein Bundler — nur Flask-Templates und Vanilla JS.

### Echtzeit-UI & Singleton-Polling

- Zentraler Spielzustand über `/api/game-state` und `/api/status`
- **Singleton-Polling:** kein Request-Overlap, adaptives Intervall (Production: aktiv 8 s / idle 12 s / hidden 30 s)
- **Server-Zeit-Sync** für drift-sichere Queue-Countdowns
- **`requestAnimationFrame`-Ticker** für Fortschrittsbalken zwischen Polls
- **`AbortController`-Lifecycle:** Polling, PJAX und Actions werden bei Navigation sauber abgebrochen

### Queue-Systeme

- **Bau-Queue** pro Planet (Limit konfigurierbar, Default 3)
- **Account-Forschungs-Queue** pro Spieler (Limit 2–3)
- **Shipyard-Queue** pro Planet
- **Planet-Forschungs-Queue** (Evolution) pro Planet
- Zentraler **Queue-Engine** (`game/queue_engine.py`) inkl. Fleet-Tick
- Atomare `BEGIN IMMEDIATE`-Transaktionen (SQLite)
- Due-Job-Finisher bei Reads und Actions
- Idempotente API-Actions mit `request_id` / `X-Request-Id`

### Admin Control Center

Operatives Dashboard unter `/admin` mit Tabs für Health, Migrationen, Spieler, Planeten, Queues, Audit-Log, Runtime und Universe-Settings. Destruktive Aktionen erfordern Bestätigungsphrasen (`BAN PLAYER`, `CLEAR QUEUE`, …).

### Health & Migrations

Bootstrap prüft in Production: sichere Config, angewandte Migrationen, beschreibbare Pfade. `/health` aggregiert alle Checks für Load Balancer, Docker und Monitoring.

### Security & Race Hardening

- Idempotency-Store (`action_idempotency`) gegen Double-Submit
- Parallel-Queue-Tests (`tests/test_race_conditions.py`)
- Legacy-DB-Hardening für alte `planets`-Schemas
- Auth-safe Polling (kein Status-Fetch auf Login/Register)
- Admin-API-Guards mit JSON-Fehlercodes statt Redirects

---

## Architektur

Kurzüberblick — Details in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

```
Browser (PJAX + Poll) → Flask (app.py) → game/* → SQLite + migrations/
```

| Schicht | Verantwortung |
|---------|---------------|
| **Backend** | Flask-Routen, Session-Auth, JSON-APIs, Jinja2 |
| **Frontend** | `templates/base.html` Shell, `static/main.js` (GC namespace) |
| **Planet Scope** | `players.active_planet_id` → `get_context_planet()` |
| **Polling** | `/api/game-state` — Ressourcen, Queues, Panels |
| **Queue Engine** | Build, Research, Shipyard, Planet-Tech, Fleet |
| **Effects** | `game/effects/effect_resolver.py` — autoritative Formeln |

### Wichtige API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/game-state` | GET | Kanonischer Live-State (Poll) |
| `/api/planets/active` | POST | Aktiven Planet wechseln |
| `/api/buildings/upgrade` | POST | Gebäude queuen (idempotent) |
| `/api/research/start` | POST | Account-Tech (idempotent) |
| `/api/fleet/send` | POST | Flotte senden |
| `/api/shipyard/build` | POST | Schiff bauen |
| `/api/exchange` | POST | Metall ↔ Kristall |
| `/api/admin/*` | GET/POST | Admin Control Center |
| `/health` | GET | System-Health (öffentlich) |

---

## Security & Stability

| Mechanismus | Implementierung |
|-------------|-----------------|
| **Idempotency** | `action_idempotency`-Tabelle; TTL-Purge beim Bootstrap |
| **Atomare Transaktionen** | `begin_write_transaction()` → `BEGIN IMMEDIATE` (SQLite) |
| **Queue-Hardening** | Queue-Limit-Check innerhalb derselben Transaktion |
| **Auth-safe Polling** | Kein Poll auf `/login`, `/register`, `/logout` |
| **Admin Audit** | Jede privilegierte Admin-API-Aktion → `admin_audit_log` |
| **Production Guards** | Insecure `SECRET_KEY`, `FLASK_DEBUG=1`, pending Migrations → Exit |
| **Legacy DB** | Migration `009_legacy_planets_hardening.sql` |
| **DB-Produktion** | **SQLite (WAL)** — Single-Writer; 1 Replica / 1 Gunicorn-Worker. Postgres-Cutover ist nicht geplant ([CAPABILITY_STATUS.md](docs/CAPABILITY_STATUS.md)) |

> **Auth:** Neue Passwörter nutzen **Argon2id**; Legacy-SHA-256 wird bei Login re-gehasht (GC-SEC-P0). Details: [docs/SECURITY.md](docs/SECURITY.md).

---

## Entwicklung (nur autorisierte Mitwirkende)

Repository-Zugang, lokale Einrichtung und Betrieb sind **nicht** für öffentliches Self-Hosting vorgesehen. Siehe [LICENSE](LICENSE) und [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md).

---

## Health System

```bash
curl -s http://127.0.0.1:5000/health | python -m json.tool
```

Beispiel-Antwort:

```json
{
  "status": "ok",
  "version": "1.5.3",
  "checks": {
    "database": {"ok": true, "backend": "sqlite", "path": "game/game.db"},
    "migrations": {"ok": true, "current": true, "pending": []},
    "writable": {"ok": true},
    "config": {"ok": true, "production": false, "debug": true}
  }
}
```

| HTTP | Bedeutung |
|------|-----------|
| `200` | `status: ok` — System gesund |
| `503` | `status: fail` — DB, Migrationen, Schreibrechte oder Production-Config fehlerhaft |
| `200` (degraded) | `status: degraded` — Nicht-kritische Config-Warnungen in Development |

Bei `503` mit pending Migrations: `python migrate.py` ausführen und App neu starten.

---

## Testing

```bash
pip install pytest
python -m pytest tests/ -v
```

Einzelne Suites:

```bash
python -m pytest tests/test_deployment.py -v
python -m pytest tests/test_persistence.py -v
python -m pytest tests/test_race_conditions.py -v
python -m pytest tests/test_admin_control_center.py -v
```

| Suite | Abdeckung |
|-------|-----------|
| `test_deployment.py` | Config-Validation, Installer, Health-Endpoint |
| `test_persistence.py` | Migrationen, Idempotency-TTL, DB-Helpers, Schema-Hardening |
| `test_race_conditions.py` | Parallele Build/Research-Queues, Idempotency-Replay |
| `test_admin_control_center.py` | Admin-API-Auth, Spieler/Queue/Audit-Operationen |
| `test_fleet.py` / `test_galaxy.py` | Flotte, Galaxie, Koordinaten |
| `test_planet_evolution*.py` | Planet Evolution, Multi-Kolonie |
| `test_trader_hub.py` / `test_exchange.py` | Trader Hub, Exchange |

Manueller Alpha-Testplan: [`docs/ALPHA_TESTPLAN.md`](docs/ALPHA_TESTPLAN.md).

---

## Admin Control Center

**Route:** `/admin` (Session + Admin-Rolle erforderlich)

| Tab | Funktion |
|-----|----------|
| **Health** | Live-Systemstatus (DB, Migrationen, Config) |
| **Migrations** | Angewandte/ausstehende Migrationen, manuelles Ausführen |
| **Players** | Suche, Ban/Unban, Admin-Rechte, Ressourcen, Homeworld-Repair |
| **Planets** | Planet-Suche, Ressourcen, Gebäude-Level, Reset |
| **Queues** | Build/Research-Queues einsehen, Jobs canceln, Due-Finish |
| **Audit** | Filterbares Audit-Log aller Admin-Aktionen |
| **Runtime** | Version, Environment, DB-Pfad, Debug-Status |
| **Settings** | Universe-Name, Speed-Faktoren, MOTD, Queue-Limits |

**Sicherheit:**

- HTML-Routen: `@require_admin` (Redirect bei fehlender Berechtigung)
- JSON-API: `@require_admin_api` (401/403 statt Redirect)
- Destruktive Aktionen: Bestätigungsphrase erforderlich
- Audit-Trail: Admin-ID, Action, Target, Payload, IP, User-Agent, Timestamp

Legacy-Formular-Routen (`/admin/update`, `/admin/ban`, …) existieren parallel zum Control Center.

---

## Projektstruktur

```
Genesis Colonies/
├── app.py                  # Flask-Einstieg, Routen, API, Bootstrap
├── migrate.py              # SQL-Migrations-Runner
├── VERSION                 # Semantische Versionsdatei (Cache-Busting)
├── requirements.txt        # Runtime-Dependencies (Flask, python-dotenv)
├── requirements-prod.txt   # + gunicorn
├── .env.example            # Dev template (authorized use only)
│
├── game/                   # Domain & Infrastruktur
│   ├── models.py           # Schema, User/Player, Idempotency
│   ├── db.py               # DB-Abstraction, Transaktionen
│   ├── bootstrap.py        # Startup: Config, DB, Migration Guard
│   ├── config.py           # Environment-Validation
│   ├── health.py           # /health Report-Assembly
│   ├── auth.py             # Session, Guards, Ban-Logik
│   ├── logic.py            # Live-State, Queue-Fassade
│   ├── queue_engine.py     # Zentraler Due-Finisher
│   ├── buildings.py        # Bau-Queue
│   ├── research.py         # Account-Forschung
│   ├── resources.py        # Produktion, Storage, Energy
│   ├── fleet*.py           # Flotte, Calc, Defs
│   ├── galaxy.py           # Koordinaten, Systemansicht
│   ├── shipyard*.py        # Schiffsbau-Queue
│   ├── exchange.py         # Trader Hub Tausch
│   ├── planet_evolution/   # Multi-Kolonie, DNA, Planet-Tech
│   ├── effects/            # EffectResolver
│   ├── chat.py, messages.py, alliance.py, …
│   └── admin*.py           # Admin Control Center
│
├── migrations/             # SQL-Migrationen (006–116)
├── templates/              # Jinja2 (base.html = SPA-Shell)
├── static/
│   ├── main.js             # PJAX, Polling, Fleet, Planet Scope
│   ├── js/chat.js, messages.js
│   └── admin.js
├── tests/                  # pytest
├── docs/                   # Master-Docs — start with WORKFLOW.md
│   ├── WORKFLOW.md         # Ticket-Workflow
│   ├── ARCHITECTURE.md
│   └── …                   # System-Docs (FLEET, GALAXY, …)
└── tools/
    └── generate_icons.py   # Asset-Generator
```

---

## Roadmap

Vollständige Phasen: [`docs/ROADMAP.md`](docs/ROADMAP.md).

| System | Status |
|--------|--------|
| Economy, Buildings, Research | ✅ |
| Multi-Kolonie, Planet Evolution | ✅ |
| Galaxy, Fleet, Shipyard, Trader Hub | ✅ |
| Combat, Defense, Fleet Logistics | ✅ |
| Alliance MVP | ✅ (Kriegs-/Diplomatie-Hooks post-Beta) |
| Security Hardening (GC-SEC-P0) | ✅ |
| Beta Gate / First-30 / Combat polish | 📋 siehe [CAPABILITY_STATUS.md](docs/CAPABILITY_STATUS.md) |
| Produktion DB | ✅ SQLite — Postgres-Cutover nicht geplant |

---

## UI/UX Direction

Genesis Colonies verfolgt eine **taktische Sci-Fi-Ästhetik** — Command-Center-HUD, klare Informationsdichte, keine generische SaaS-Bubble-UI.

- **Resource Bar:** Ferronit, Crytite, Brennzellen, Aetherion (Energie)
- **Planet Switcher:** Header-Dropdown bei 2+ Kolonien
- **Navigation:** Desktop-Sidebar + Mobile Bottom-Nav
- **Admin:** Eigenes OPS-Design (`OPS // UNIVERSE COMMAND`)
- **Motion:** Score-Delta-Pops, Queue-Fortschritt per rAF, dezente Übergänge
- **Accessibility:** `aria-live` auf Resource Bar, semantische Tab-Struktur im Admin

Ressourcen: **Ferronit** (Metal), **Crytite** (Crystal), **Brennzellen** (Fuel), **Aetherion** (Energie).

---

## Contributing

Entwicklung als **Tickets** (GC-XXX) — siehe [`docs/WORKFLOW.md`](docs/WORKFLOW.md).

1. Master-Doc lesen → Ticket-Scope (max. 3–5 Dateien)
2. `python scripts/install.py --venv`
3. Migrationen: `migrations/NNN_*.sql`
4. `python -m pytest tests/ -v` grün
5. Details: [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md)

---

## Spielstand / Datenbank

- SQLite-Datei: `game/game.db` (oder Pfad aus `GC_DB_PATH`)
- In `.gitignore` — wird nicht committed
- **Backup** vor Updates empfohlen
- Migrationen: `python migrate.py` (idempotent, History in `migration_history`)

---

## Lizenz

**Proprietär — All Rights Reserved.** Siehe [LICENSE](LICENSE).

Unbefugtes Kopieren, Hosten, Deployen oder Weiterverbreiten ist untersagt. Genesis Colonies wird ausschließlich vom Projekt betrieben.

**Early Alpha** — API, Schema und Spielbalance können sich ändern.

---

## Weiterführende Dokumentation

**Start:** [`docs/WORKFLOW.md`](docs/WORKFLOW.md) — Ticket-Workflow & Master-Doc-Index

| Dokument | Inhalt |
|----------|--------|
| [`docs/CAPABILITY_STATUS.md`](docs/CAPABILITY_STATUS.md) | Was es kann / was es noch verträgt |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Systemdesign, Module, APIs |
| [`docs/PLANET_SCOPE.md`](docs/PLANET_SCOPE.md) | Aktiver Planet, Multi-Kolonie |
| [`docs/PLANET_EVOLUTION.md`](docs/PLANET_EVOLUTION.md) | DNA, Planet-Tech, Events |
| [`docs/FLEET_SYSTEM.md`](docs/FLEET_SYSTEM.md) | Flotten, Missionen |
| [`docs/GALAXY_SYSTEM.md`](docs/GALAXY_SYSTEM.md) | Koordinaten, Systemansicht |
| [`docs/ECONOMY_SYSTEM.md`](docs/ECONOMY_SYSTEM.md) | Ressourcen, Trader Hub |
| [`docs/BUILDINGS_SYSTEM.md`](docs/BUILDINGS_SYSTEM.md) | Gebäude, Bau-Queue |
| [`docs/RESEARCH_SYSTEM.md`](docs/RESEARCH_SYSTEM.md) | Account-Forschung |
| [`docs/EFFECTS.md`](docs/EFFECTS.md) | EffectResolver |
| [`docs/STATE_AJAX.md`](docs/STATE_AJAX.md) | Polling, PJAX |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Phasen, Meilensteine |
| [`docs/TICKET_TEMPLATE.md`](docs/TICKET_TEMPLATE.md) | Ticket-Vorlage |
| [`docs/CONTRIBUTING.md`](docs/CONTRIBUTING.md) | Code-Stil, PR |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat Model |
| [`docs/ALPHA_TESTPLAN.md`](docs/ALPHA_TESTPLAN.md) | Manuelle QA |
