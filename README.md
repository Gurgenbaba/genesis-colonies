# Genesis Colonies

Browser-basiertes Strategiespiel (OGame-inspiriert) mit **Flask**, **SQLite** und **Jinja2**.  
Wirtschaftskern (Bauen, Forschen, Ranking) ist spielbar; Militär/Expansion folgen schrittweise.

---

## Voraussetzungen

- **Python 3.10+** (getestet mit 3.13)
- **pip**
- Optional: Git

Kein Node.js, kein Docker nötig.

---

## Installation (Windows / PowerShell)

```powershell
cd "C:\Users\gurge\Desktop\RandomStuff\Coding\Genesis Colonies"
python scripts/install.py --venv --admin
.\.venv\Scripts\Activate.ps1
```

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for Linux VPS, Docker, updates, and production checklist.

---

## Starten

```powershell
python app.py
```

**URL:** [http://127.0.0.1:5000](http://127.0.0.1:5000)

Server stoppen: `Strg + C`

---

## Erster Login

| Option | Beschreibung |
|--------|--------------|
| **Registrieren** | [http://127.0.0.1:5000/register](http://127.0.0.1:5000/register) |
| **Admin (nur frische DB)** | Wenn noch **kein** User existiert: `admin` / `admin` |

> **Hinweis:** Default-Admin wird nur bei leerer Datenbank angelegt.  
> Passwort-Hashing ist derzeit SHA-256 — nur für lokale Entwicklung gedacht.

---

## Spielstand / Datenbank

- SQLite-Datei: `game/game.db`
- **Nicht löschen**, wenn du Fortschritt behalten willst
- In `.gitignore` eingetragen — wird nicht ins Repo committed
- Zusätzliche SQL-Migrationen (optional): `python migrate.py` (nur wenn `game/game.db` existiert)

---

## Was ist spielbar?

| Seite | Route | Status |
|-------|-------|--------|
| Landing | `/` | ✅ |
| Registrierung / Login | `/register`, `/login` | ✅ |
| Übersicht | `/overview` | ✅ Live-Ressourcen, Queues |
| Gebäude | `/buildings` | ✅ Bauen, Upgrade, Queue |
| Forschung | `/research` | ✅ Techs, Queue |
| Tech-Tree | `/techtree` | ✅ Visualisierung |
| Ranking | `/ranking` | ✅ |
| Admin | `/admin` | ✅ (nur Admin) |

## Work in Progress (UI-Vorschau)

| Seite | Route |
|-------|-------|
| Galaxie | `/galaxy` |
| Werft | `/shipyard` |
| Verteidigung | `/defense` |
| Flotte | `/fleet` |
| Allianz | `/alliance` |

Diese Module zeigen Layout und Navigation; Spielmechanik folgt später.

---

## Projektstruktur (kurz)

```
app.py              # Flask-Einstieg, Routen
game/               # Logik, Models, SQLite
templates/          # Jinja2-HTML
static/             # CSS, JS
locales/de.json     # Texte (DE)
migrations/         # Optionale SQL-Migrationen
migrate.py          # Migrations-Runner
```

---

## Manueller Test

Siehe [docs/ALPHA_TESTPLAN.md](docs/ALPHA_TESTPLAN.md).

---

## Lizenz / Status

Early Alpha — use `docs/DEPLOYMENT.md` for production setup. Health: `GET /health`.
