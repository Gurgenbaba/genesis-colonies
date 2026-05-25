# Genesis Colonies — Contributing

Richtlinien für Entwickler, die am Projekt mitarbeiten. Ziel: konsistente, reviewbare Beiträge ohne Regressionen in Queues, Migrationen oder Deployment.

---

## Voraussetzungen

| Tool | Version |
|------|---------|
| Python | 3.10+ (empfohlen 3.13) |
| pip | aktuell |
| pytest | separat installieren (`pip install pytest`) |
| Git | optional |

Kein Node.js, kein Docker (optional für Deployment-Tests).

---

## Ersteinrichtung

```bash
git clone <repo-url> genesis-colonies
cd genesis-colonies
python scripts/install.py --venv --admin
source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
python app.py
```

Health prüfen:

```bash
curl -s http://127.0.0.1:5000/health
```

Ausführlich: [README](../README.md), [DEPLOYMENT.md](DEPLOYMENT.md).

---

## Branch-Workflow

1. Von `main` (oder aktuellem Default-Branch) abzweigen
2. Branch-Namen: `feature/kurzbeschreibung`, `fix/issue-beschreibung`, `docs/thema`
3. Kleine, fokussierte PRs bevorzugen (ein Feature / ein Fix pro PR)
4. Vor PR: Tests laufen lassen (siehe unten)
5. Beschreibung: **Was**, **Warum**, **Wie getestet**

---

## Code-Stil

### Python (`game/`, `app.py`)

- Bestehende Konventionen im Modul beibehalten
- Typ-Hints wo bereits üblich (`from __future__ import annotations`)
- Keine unnötigen Abstraktionen — lieber bestehende Funktion erweitern
- DB-Zugriffe: `game/db.py`-Helpers nutzen (`begin_write_transaction`, `with_transaction`)
- **Conn-safe:** Wenn `conn` übergeben wird, kein eigenes `commit()` in Subfunktionen ohne Absprache
- Fehler in Game-Logic: `(ok: bool, reason: str, payload)` — nicht Exceptions für erwartbare Spielregeln

### JavaScript (`static/main.js`, `static/admin.js`)

- IIFE + `"use strict"` beibehalten
- Kein globales Pollution — `GC`-Namespace erweitern
- Bei Navigation: `GC.registerCleanup()` oder `GC.cleanupPage()`-kompatibel
- Keine neuen Frameworks ohne Architektur-Entscheid

### Templates

- Jinja2, `{% extends "base.html" %}` für Ingame-Seiten
- Texte über `T("key")` / `locales/de.json` (primär DE)
- Admin: defensive Defaults wie in `admin_panel.html`

### CSS

- `static/style.css` — tactical Sci-Fi, bestehende CSS-Variablen/Klassen nutzen
- Admin: `static/admin.css`

---

## Datenbank & Migrationen

### Regel

**Jede Schema-Änderung = neue SQL-Datei in `migrations/`**, nie nur `init_db()` anpassen ohne Migration (bestehende Installationen!).

### Namenskonvention

```
migrations/NNN_kurz_beschreibung.sql
```

- `NNN` = dreistellig, aufsteigend (aktuell bis `010`)
- Lowercase, Underscores
- Idempotente Statements bevorzugen: `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`
- `ALTER TABLE ADD COLUMN` — Runner überspringt `duplicate column name`

### Migration testen

```bash
# Frische DB
rm -f /tmp/test.db
export GC_DB_PATH=/tmp/test.db
python -c "from game.bootstrap import bootstrap_application; bootstrap_application(skip_migration_check=True)"
python migrate.py
python migrate.py   # zweiter Lauf: "bereits angewendet"
```

Relevante Tests: `tests/test_persistence.py`

### Bootstrap-Verhalten

- **Development:** Pending Migrations → Warning, App startet
- **Production:** Pending Migrations → Exit

In Tests: `GC_SKIP_MIGRATION_CHECK=1` setzen.

---

## Tests

### Suite ausführen

```bash
pip install pytest
python -m pytest tests/ -v
```

Erwartung: **alle Tests grün** (aktuell 31 Tests).

### Wann welcher Test

| Änderung an | Test-Datei |
|-------------|------------|
| Queues, parallele Actions | `test_race_conditions.py` |
| DB, Migrationen, Idempotency | `test_persistence.py` |
| Config, Installer, Health | `test_deployment.py` |
| Admin-API | `test_admin_control_center.py` |

### Neuen Test schreiben

- Isolierte DB via `tmp_path` + `monkeypatch.setenv("GC_DB_PATH", ...)`
- `models.init_db()` oder `bootstrap_application(skip_migration_check=True)`
- Keine Abhängigkeit von `game/game.db` im Repo
- Keine flaky Sleeps — Parallelität über `ThreadPoolExecutor` wie in Race-Tests

Beispiel-Fixture-Muster: siehe `tests/test_race_conditions.py`.

### Was nicht testen

- Triviale Getter ohne Logik
- Reine CSS-Farbänderungen (manuell laut [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md))

---

## API-Änderungen

Neue Spieler-APIs:

1. Route in `app.py` mit `@require_login`
2. Business Logic in `game/` (nicht in `app.py` aufblähen)
3. Actions: Idempotenz via `request_id` / `X-Request-Id` unterstützen
4. Antwort: `_action_json_response()` oder konsistentes `{ ok, state }`
5. `static/main.js`: `GC.fetchGameAction()` nutzen

Neue Admin-APIs:

1. Logik in `game/admin_api.py`
2. `@require_admin_api` in `app.py`
3. `audit()` für mutierende Aktionen
4. Destruktiv → `CONFIRM_PHRASES` + `validate_confirm()`
5. Client in `static/admin.js`

---

## Umgebungsvariablen in Tests

```python
monkeypatch.setenv("GC_DB_PATH", str(db_file))
monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
monkeypatch.setenv("APP_ENV", "development")
monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
```

Niemals echte Production-`SECRET_KEY` oder `game/game.db` in Tests verwenden.

---

## Commit-Messages

Imperativ, Englisch oder Deutsch — konsistent innerhalb eines PRs.

```
feat: add asteroid resource tick for galaxy prep
fix: prevent research queue overflow on parallel POST
docs: extend ARCHITECTURE with PJAX lifecycle
test: cover idempotency TTL expiry
```

Typen: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`

---

## Pull-Request-Checkliste

- [ ] Fokussierter Diff (kein unrelated Formatting)
- [ ] `python -m pytest tests/ -v` grün
- [ ] Neue Migrationen: `migrate.py` auf frischer DB getestet
- [ ] `/health` ok nach lokalem Start (wenn Infra betroffen)
- [ ] Locales: neue UI-Strings in `locales/de.json` (und `en.json` wenn sinnvoll)
- [ ] Keine Secrets in Git (`.env`, `game/game.db`, `__pycache__`)
- [ ] Security-relevant: [SECURITY.md](SECURITY.md) gelesen

---

## Manuelle QA

Für UI/UX-Änderungen zusätzlich [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — mindestens Auth, Overview, Buildings, Research, Mobile-Nav.

---

## Dokumentation

| Änderung | Datei aktualisieren |
|----------|---------------------|
| Neue Env-Variable | `.env.example`, `docs/DEPLOYMENT.md`, README |
| Architektur / Flow | `docs/ARCHITECTURE.md` |
| Security-Verhalten | `docs/SECURITY.md` |
| Meilenstein / Feature-Plan | `docs/ROADMAP.md` |

---

## Fragen & Scope

- **Spielbalance** (Kosten, Zeiten): mit Projektleitung abstimmen
- **Breaking API-Changes:** Version bump in `VERSION` + README-Hinweis
- **Große Refactors:** vorher Issue/Discussion — kleine inkrementelle PRs bevorzugt

---

## Verwandte Dokumente

- [README](../README.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [SECURITY.md](SECURITY.md)
- [ROADMAP.md](ROADMAP.md)
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md)
