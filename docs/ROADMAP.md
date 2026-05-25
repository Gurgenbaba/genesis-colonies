# Genesis Colonies — Roadmap

Geplante Entwicklungsphasen und Meilensteine. Stand: **v1.5.1** (Alpha).

Status-Legende:

| Symbol | Bedeutung |
|--------|-----------|
| ✅ | Fertig / stabil |
| 🔄 | In Arbeit / teilweise |
| 📋 | Geplant |
| 💡 | Idee / Backlog |

---

## Phase 0 — Foundation ✅

Infrastruktur und Architektur-Basis (abgeschlossen).

| Item | Status |
|------|--------|
| Flask + SQLite + Jinja2 | ✅ |
| Installer (`scripts/install.py`) | ✅ |
| Environment & Config Guards | ✅ |
| SQL-Migrationen (`006`–`010`) | ✅ |
| Health Endpoint (`/health`) | ✅ |
| Docker + Gunicorn Deployment | ✅ |
| DB-Abstraction (`game/db.py`) | ✅ |
| Bootstrap & Migration Guard | ✅ |
| pytest-Suite (31 Tests) | ✅ |

---

## Phase 1 — Economy Core ✅

Spielbarer Wirtschaftskern.

| Item | Status |
|------|--------|
| Auth (Register/Login/Logout) | ✅ |
| Ressourcen-Tick (Ferronit, Crytite, Aetherion) | ✅ |
| Gebäude bauen / upgraden | ✅ |
| Bau-Queue mit Limit | ✅ |
| Forschung + Queue | ✅ |
| Tech-Tree Visualisierung | ✅ |
| Ranking & Player Scores | ✅ |
| SPA/PJAX Navigation | ✅ |
| Live-Polling + rAF Queue-UI | ✅ |
| Idempotente Build/Research APIs | ✅ |
| Race-safe Queue Tests | ✅ |

---

## Phase 2 — Operations & Admin ✅

Betrieb und Administration.

| Item | Status |
|------|--------|
| Admin Control Center (8 Tabs) | ✅ |
| Admin JSON API (`/api/admin/*`) | ✅ |
| Audit Log | ✅ |
| Queue-Management (cancel, finish-due, clear) | ✅ |
| Player/Planet-Tools | ✅ |
| Legacy Admin Forms (parallel) | ✅ |
| MOTD & Universe Settings | ✅ |
| Ban-System | ✅ |

---

## Phase 3 — Security Hardening 📋

Vor öffentlichem Production-Launch.

| Item | Priorität | Status |
|------|-----------|--------|
| Passwort-KDF (bcrypt/argon2) | P0 | 📋 |
| Rate-Limiting Login/Register | P0 | 📋 |
| Session-Cookie Flags (`Secure`, `SameSite`) | P1 | 📋 |
| CSRF-Schutz HTML-Forms | P1 | 📋 |
| Security-Headers (HSTS, nosniff) | P2 | 📋 |
| Failed-Login-Logging | P2 | 📋 |

Details: [SECURITY.md](SECURITY.md)

---

## Phase 4 — Military & Expansion 🔄

Kampf und Reichweite — UI-Vorschau existiert, Mechanik fehlt.

| Item | Status | Abhängigkeiten |
|------|--------|----------------|
| **Galaxie** — Karte, Slots, Kolonisierung | 📋 UI ✅ | Planet-Modell, Koordinaten-System |
| **Werft** — Schiffsbau, Queue | 📋 UI ✅ | Tech-Tree, Ressourcen, Queue-Pattern |
| **Verteidigung** — Türme, Schilder | 📋 UI ✅ | Gebäude-System, Kampf-Formeln |
| **Flotte** — Missionen, Bewegung | 📋 UI ✅ | Werft, Galaxie, Travel-Time |
| Kampf-Auflösung (Kampfberichte) | 📋 | Flotte, Verteidigung |
| Espionage | 💡 | Forschung, Galaxie |

Empfohlene Reihenfolge:

```
Galaxie (Koordinaten) → Werft (Units) → Flotte (Movement) → Verteidigung → Combat Resolver
```

---

## Phase 5 — Social & Meta 📋

| Item | Status | Notizen |
|------|--------|---------|
| **Allianz** — Gründung, Mitglieder, Rechte | 📋 UI ✅ | Eigene Tabellen, Permissions |
| **PlayerCard** — Profil, Stats, Historie | 📋 | Ranking-Daten wiederverwenden |
| **Chat** — Allianz / Universe | 📋 | Redis oder Polling; Moderation |
| **Marketplace** — Handel | 💡 | Economy-Balance kritisch |
| Nachrichten / Berichte-Inbox | 💡 | Flottenberichte, System-Mails |

---

## Phase 6 — Platform & Scale 📋

| Item | Status | Notizen |
|------|--------|---------|
| PostgreSQL Backend | 📋 | Hooks in `game/db.py` vorhanden |
| Horizontale Skalierung (Multi-Worker) | 📋 | Benötigt Postgres + Locks |
| Redis Sessions/Cache | 💡 | `REDIS_URL` in `.env.example` |
| E-Mail (`MAIL_*`) | 💡 | Registrierung, Berichte |
| WebSocket Push (optional) | 💡 | Polling als Fallback behalten |
| i18n UI-Switch (DE/EN) | 🔄 | `en.json` existiert; `GC_LOCALE` hardcoded `de` |
| CDN / Asset-Pipeline | 💡 | Aktuell statische Dateien + `VERSION` Cache-Bust |

---

## Phase 7 — Polish & Live Ops 💡

| Item | Status |
|------|--------|
| Balancing-Tooling (Admin) | 💡 |
| Analytics / Metrics Export | 💡 |
| Automated Backups (Operator-Docs) | 📋 teilweise in DEPLOYMENT |
| Bugbot / CI Pipeline | 💡 |
| Tutorial / Onboarding Flow | 💡 |
| Season / Universe-Reset-Zyklen | 💡 |

---

## Meilenstein-Übersicht (Timeline-Richtung)

```
2025 Q1–Q2   Phase 0–2 ✅  Foundation, Economy, Admin
2025 Q3      Phase 3       Security Hardening
2025 Q4      Phase 4a      Galaxie + Werft (spielbar)
2026 Q1      Phase 4b      Flotte + Verteidigung + Combat
2026 Q2      Phase 5       Allianz + Chat
2026+        Phase 6       Postgres, Scale, i18n
```

*Timeline ist orientierend — keine festen Release-Daten.*

---

## Technische Schulden (bekannt)

| Thema | Impact | Ziel-Phase |
|-------|--------|------------|
| SHA-256 Passwörter | Security | Phase 3 |
| Kein Rate-Limiting | Abuse | Phase 3 |
| `GC_LOCALE` hardcoded | i18n | Phase 6 |
| Legacy Admin Forms doppelt | Wartung | Phase 2→3 Cleanup |
| SQLite Single-Writer | Scale | Phase 6 |
| WIP-Seiten ohne Backend | UX-Erwartung | Phase 4 |

---

## Wie Roadmap-Items priorisieren

1. **Spieler-sichtbarer Wert** — neue Mechanik schlägt Refactor
2. **Security vor Launch** — Phase 3 blockiert Public Beta
3. **Wiederverwendung** — Queues, Idempotenz, Admin-Muster für neue Module nutzen
4. **Tests mitliefern** — jede Queue/DB-Änderung braucht pytest-Abdeckung

Vorschläge: Issue mit Label `roadmap` + Verweis auf Phase.

---

## Verwandte Dokumente

- [README](../README.md) — Aktueller Feature-Status
- [ARCHITECTURE.md](ARCHITECTURE.md) — Erweiterungspunkte im Code
- [SECURITY.md](SECURITY.md) — Phase-3-Details
- [CONTRIBUTING.md](CONTRIBUTING.md) — Beitrags-Workflow
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle Tests pro Release
