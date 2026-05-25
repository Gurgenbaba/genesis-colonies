# Genesis Colonies

**Build. Research. Command the cluster.**

Browser-basiertes Sci-Fi-Strategiespiel (OGame-inspiriert) — entwickelt als production-ready Web-App mit Flask, SQLite und einer SPA/PJAX-Frontend-Schicht ohne Build-Toolchain.

| | |
|---|---|
| **Version** | `1.5.1` (siehe [`VERSION`](VERSION)) |
| **Stack** | Python 3.10+ · Flask 3 · SQLite (WAL) · Vanilla JS |
| **Status** | Alpha — Wirtschaftskern spielbar, Militär/Expansion in Entwicklung |
| **Health** | `GET /health` |

---

## Projektübersicht

Genesis Colonies ist ein persistentes Browser-Strategiespiel, in dem Spieler eine Kolonie aufbauen, Ressourcen produzieren, Gebäude erweitern und Technologien erforschen. Das Backend liefert serverseitige Spielmechanik; das Frontend aktualisiert Ressourcen, Queues und UI-Zustände in Echtzeit — ohne Full-Page-Reloads.

**Ziel:** Ein ernsthaft entwickeltes, selbst gehostetes Strategiespiel mit klarer Architektur, reproduzierbarem Deployment und operativen Werkzeugen für Admins.

**Vision:** Von der spielbaren Wirtschaftskern-Phase zu Galaxie, Flotten, Allianzen und Multiplayer-Systemen — auf einer Basis, die Race Conditions, Idempotenz und Migrationen von Anfang an berücksichtigt.

---

## Aktueller Status

### Stabil / produktionsreif (Infrastruktur)

| Bereich | Stand |
|---------|-------|
| Installer & Bootstrap | `scripts/install.py`, `.env`-Setup, Migration Guard |
| Deployment | Gunicorn, Docker, systemd-Vorlage ([`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)) |
| Health Monitoring | `GET /health` mit DB-, Migrations-, Config- und Write-Checks |
| DB-Migrationen | Versioniertes SQL-System (`migrations/`, `migrate.py`) |
| Admin Control Center | JSON-API + operatives UI (`/admin`, `/api/admin/*`) |
| Audit Logging | `admin_audit_log` für privilegierte Aktionen |
| Frontend-Architektur | SPA/PJAX, Singleton-Polling, Lifecycle-Cleanup |
| Queue-Hardening | Atomare Transaktionen, Idempotenz, Parallel-Tests |
| Test-Suite | 31 pytest-Tests (Deployment, Persistence, Race Conditions, Admin) |

### Spielbar (Mechanik)

| Modul | Route | Status |
|-------|-------|--------|
| Landing | `/` | ✅ |
| Auth | `/register`, `/login`, `/logout` | ✅ |
| Übersicht | `/overview` | ✅ Live-Ressourcen, Queues |
| Gebäude | `/buildings` | ✅ Bauen, Upgrade, Queue |
| Forschung | `/research` | ✅ Techs, Queue |
| Tech-Tree | `/techtree` | ✅ Visualisierung |
| Ranking | `/ranking` | ✅ Score & Rangliste |
| Admin | `/admin` | ✅ Control Center (Admin only) |

### UI-Vorschau (Layout & Navigation, Mechanik folgt)

| Modul | Route |
|-------|-------|
| Galaxie | `/galaxy` |
| Werft | `/shipyard` |
| Verteidigung | `/defense` |
| Flotte | `/fleet` |
| Allianz | `/alliance` |

---

## Kernfeatures

### SPA/PJAX ohne Framework

Navigation zwischen Ingame-Seiten erfolgt per PJAX (`X-PJAX: true`): Flask liefert HTML-Fragmente, `static/main.js` tauscht den Content-Bereich aus. Kein Node.js, kein Bundler — nur Flask-Templates und Vanilla JS.

### Echtzeit-UI & Singleton-Polling

- Zentraler Spielzustand über `/api/game-state` und `/api/status`
- **Singleton-Polling:** kein Request-Overlap, adaptives Intervall (aktiv 1 s / idle 4 s / hidden 12 s)
- **Server-Zeit-Sync** für drift-sichere Queue-Countdowns
- **`requestAnimationFrame`-Ticker** für Fortschrittsbalken zwischen Polls
- **`AbortController`-Lifecycle:** Polling, PJAX und Actions werden bei Navigation sauber abgebrochen

### Queue-Systeme

- **Bau-Queue** pro Planet (Limit konfigurierbar, Default 3)
- **Forschungs-Queue** pro Spieler (eine aktive Forschung)
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

```
┌─────────────────────────────────────────────────────────────┐
│  Browser (Vanilla JS — static/main.js)                      │
│  PJAX Navigation · Singleton Poll · rAF Ticker · Actions    │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (HTML + JSON)
┌──────────────────────────▼──────────────────────────────────┐
│  Flask (app.py)                                             │
│  Routes · Templates · /api/* · /api/admin/* · /health       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  game/ — Domain Layer                                       │
│  logic · buildings · research · resources · ranking · auth  │
│  admin · admin_api · admin_audit · bootstrap · health       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  game/db.py — DB Abstraction                                │
│  SQLite (WAL) · with_transaction · Postgres hooks (future)  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  SQLite (game/game.db) + migrations/*.sql                   │
└─────────────────────────────────────────────────────────────┘
```

| Schicht | Verantwortung |
|---------|---------------|
| **Backend** | Flask-Routen, Session-Auth, JSON-APIs, Jinja2-Rendering |
| **Frontend** | PJAX-Shell in `templates/base.html`, Logik in `static/main.js` |
| **DB Layer** | `game/db.py` — Connections, Transaktionen, Schema-Helpers |
| **Lifecycle** | `game/bootstrap.py` — Config, `init_db`, Migration Guard |
| **Polling** | `/api/game-state` liefert Ressourcen, Queues, Score, Panel-Daten |
| **Queue Engine** | `game/buildings.py`, `game/research.py`, `game/resources.py` |
| **Admin APIs** | `game/admin_api.py` — Business Logic für `/api/admin/*` |

### Wichtige API-Endpunkte

| Endpunkt | Methode | Beschreibung |
|----------|---------|--------------|
| `/api/status` | GET | Spielzustand (Polling) |
| `/api/game-state` | GET | Spielzustand inkl. Buildings-Panel |
| `/api/buildings/upgrade` | POST | Gebäude in Queue (idempotent) |
| `/api/research/start` | POST | Forschung starten (idempotent) |
| `/api/admin/*` | GET/POST | Admin Control Center (JSON) |
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
| **Postgres-Richtung** | `GC_DB_BACKEND=postgres` reserviert; Row-Lock-Hooks in `game/db.py` |

> **Hinweis Auth:** Passwörter werden derzeit per SHA-256 gehasht — ausreichend für lokale Entwicklung, **nicht** für Production. Vor einem öffentlichen Launch sollte ein moderner KDF (z. B. bcrypt/argon2) eingeführt werden.

---

## Installation

### Voraussetzungen

- **Python 3.10+** (getestet mit 3.13)
- **pip**
- Optional: Git, Docker

Kein Node.js erforderlich.

### Windows (PowerShell)

```powershell
cd "C:\path\to\Genesis Colonies"
py -3 scripts\install.py --venv --admin
.\.venv\Scripts\Activate.ps1
python app.py
```

### Linux / macOS

```bash
git clone <repo-url> genesis-colonies
cd genesis-colonies
python3 scripts/install.py --venv --admin
source .venv/bin/activate
python app.py
```

**URL:** [http://127.0.0.1:5000](http://127.0.0.1:5000)

Der Installer (`scripts/install.py`) führt aus:

1. Python-Version prüfen
2. Optional `.venv` anlegen und Dependencies installieren
3. `.env.example` → `.env` kopieren (falls fehlend)
4. `init_db` + `python migrate.py`
5. Schreibrechte und Migrationen verifizieren
6. Optional Admin-Account anlegen

---

## Environment

Kopiere `.env.example` nach `.env` und passe Werte an:

| Variable | Pflicht (Prod) | Beschreibung |
|----------|----------------|--------------|
| `SECRET_KEY` | **Ja** | Session-Signing — zufälliger Hex-String |
| `APP_ENV` | Ja | `production` oder `development` |
| `FLASK_DEBUG` | Ja | Muss `0` in Production sein |
| `GC_DB_BACKEND` | Nein | `sqlite` (Default); `postgres` reserviert |
| `GC_DB_PATH` | Nein | SQLite-Pfad (Default: `game/game.db`) |
| `DATABASE_URL` | Nein | Alternative: `sqlite:///game/game.db` |
| `HOST` / `PORT` | Nein | Dev-Server (Default: `127.0.0.1:5000`) |
| `GC_SKIP_MIGRATION_CHECK` | Nein | Nur CI/Tests — Migration Guard überspringen |

Secret Key generieren:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Production:** Einzigartigen `SECRET_KEY` setzen, `APP_ENV=production`, `FLASK_DEBUG=0`. Details und systemd/nginx-Beispiele: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

---

## Health System

```bash
curl -s http://127.0.0.1:5000/health | python -m json.tool
```

Beispiel-Antwort:

```json
{
  "status": "ok",
  "version": "1.5.1",
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

Manueller Alpha-Testplan: [`docs/ALPHA_TESTPLAN.md`](docs/ALPHA_TESTPLAN.md).

---

## Deployment

### Development

```bash
python app.py
```

### Production (Gunicorn)

```bash
pip install -r requirements-prod.txt
gunicorn -w 2 -b 127.0.0.1:5000 --timeout 120 app:app
```

Reverse Proxy (nginx/Caddy) für TLS davor setzen.

### Docker

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
docker compose up --build -d
curl http://127.0.0.1:5000/health
```

Daten persistieren im Volume `gc_data` (`GC_DB_PATH=/data/game.db`).

### Updates

```bash
git pull
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python migrate.py
# App / Container neu starten
curl -s http://127.0.0.1:5000/health
```

Vollständige Checkliste: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

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
├── Dockerfile              # Production-Image mit Healthcheck
├── docker-compose.yml      # Single-Service-Deployment
├── .env.example            # Environment-Template
│
├── game/                   # Domain & Infrastruktur
│   ├── models.py           # Schema, User/Player, Idempotency
│   ├── db.py               # DB-Abstraction, Transaktionen
│   ├── bootstrap.py        # Startup: Config, DB, Migration Guard
│   ├── config.py           # Environment-Validation
│   ├── health.py           # /health Report-Assembly
│   ├── auth.py             # Session, Guards, Ban-Logik
│   ├── logic.py            # Ressourcen-Tick, Queue-Fassade
│   ├── buildings.py        # Bau-Queue, Upgrades
│   ├── research.py         # Forschungs-Queue
│   ├── resources.py        # Produktion, Storage, Energy
│   ├── ranking.py          # Score-Cache, Rangliste
│   ├── techtree.py         # Tech-Tree-Daten
│   ├── admin.py            # Legacy Admin-Form-Actions
│   ├── admin_api.py        # Admin Control Center Business Logic
│   ├── admin_audit.py      # Audit-Log Schreiben/Lesen
│   └── migrations_util.py  # Migration-Status für Bootstrap/Health
│
├── migrations/             # Versionierte SQL-Migrationen (006–010)
├── templates/              # Jinja2 HTML (base.html = SPA-Shell)
├── static/
│   ├── main.js             # SPA/PJAX, Polling, Actions, Ticker
│   ├── style.css           # Tactical Sci-Fi UI
│   ├── admin.js            # Admin Control Center Client
│   └── admin.css
├── locales/
│   ├── de.json             # Primäre UI-Texte (DE)
│   └── en.json             # Englische Texte (vorbereitet)
├── scripts/
│   └── install.py          # Installer / First-Time Setup
├── tests/                  # pytest-Suite (31 Tests)
├── docs/
│   ├── DEPLOYMENT.md       # VPS, Docker, systemd, Checkliste
│   └── ALPHA_TESTPLAN.md   # Manueller Testplan
└── tools/
    └── generate_icons.py   # Asset-Generator
```

---

## Roadmap / Geplante Systeme

| System | Beschreibung | Status |
|--------|--------------|--------|
| **Galaxie** | Planeten-Karte, Koordinaten, Expansion | UI-Vorschau |
| **Werft** | Schiffsbau, Flottenkomposition | UI-Vorschau |
| **Verteidigung** | Verteidigungsanlagen | UI-Vorschau |
| **Flotte** | Flottenbewegung, Missionen | UI-Vorschau |
| **Allianz** | Spieler-Bündnisse, Diplomatie | UI-Vorschau |
| **PlayerCard** | Spieler-Profile, Statistiken | Geplant |
| **Marketplace** | Handel zwischen Spielern | Geplant |
| **Chat** | Ingame-Kommunikation | Geplant |
| **PostgreSQL** | `GC_DB_BACKEND=postgres`, Row-Locks | Infrastruktur vorbereitet |
| **Redis** | Session/Cache (`REDIS_URL`) | Reserviert in `.env.example` |
| **Mail** | Benachrichtigungen (`MAIL_*`) | Reserviert in `.env.example` |
| **Auth-Hardening** | bcrypt/argon2 statt SHA-256 | Vor Public Launch |

---

## UI/UX Direction

Genesis Colonies verfolgt eine **taktische Sci-Fi-Ästhetik** — Command-Center-HUD, klare Informationsdichte, keine generische SaaS-Bubble-UI.

- **Resource Bar:** Sticky HUD-Strip mit Live-Werten (Ferronit, Crytite, Aetherion)
- **Navigation:** Desktop-Sidebar + Mobile Bottom-Nav + „Mehr“-Drawer
- **WIP-Badge:** Galaxie, Werft, Flotte etc. als „Dev“ markiert
- **Admin:** Eigenes OPS-Design (`OPS // UNIVERSE COMMAND`)
- **Motion:** Score-Delta-Pops, Queue-Fortschritt per rAF, dezente Übergänge
- **Accessibility:** `aria-live` auf Resource Bar, semantische Tab-Struktur im Admin

Ressourcen-Naming: **Ferronit** (Metal), **Crytite** (Crystal), **Aetherion** (Energy).

---

## Contributing

1. **Fork & Branch** — Feature-Branches von `main`
2. **Setup** — `python scripts/install.py --venv`
3. **Migrationen** — Neue Schema-Änderungen als nummerierte `migrations/NNN_beschreibung.sql`
4. **Tests** — `python -m pytest tests/ -v` muss grün sein
5. **Scope** — Fokussierte Diffs; keine unrelated Refactors
6. **Commit-Stil** — Imperativ, warum vor was (`fix: prevent double queue enqueue under parallel POST`)

Bei DB-Änderungen immer `migrate.py` testen und `/health` prüfen.

---

## Spielstand / Datenbank

- SQLite-Datei: `game/game.db` (oder Pfad aus `GC_DB_PATH`)
- In `.gitignore` — wird nicht committed
- **Backup** vor Updates empfohlen
- Migrationen: `python migrate.py` (idempotent, History in `migration_history`)

---

## Lizenz / Disclaimer

**Early Alpha** — API, Schema und Spielbalance können sich ändern. Nicht für ungesicherte Production-Deployments ohne eigene Security-Review geeignet.

Keine explizite Open-Source-Lizenz im Repository hinterlegt. Nutzung und Weiterverbreitung nur nach Absprache mit den Projektverantwortlichen.

---

## Weiterführende Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | VPS, Docker, Gunicorn, systemd, Troubleshooting |
| [`docs/ALPHA_TESTPLAN.md`](docs/ALPHA_TESTPLAN.md) | Manueller Alpha-Testplan |

**Empfohlene Erweiterungen** (noch nicht im Repo):

- `docs/ARCHITECTURE.md` — Detaillierte Sequenzdiagramme (Polling, Queues, PJAX)
- `docs/SECURITY.md` — Threat Model, Auth-Roadmap, Operator-Checkliste
- `docs/CONTRIBUTING.md` — Erweiterte Dev-Guidelines, PR-Template
- `docs/ROADMAP.md` — Milestones mit Prioritäten und Abhängigkeiten
