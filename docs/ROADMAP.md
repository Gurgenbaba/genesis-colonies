# Genesis Colonies — Roadmap

Geplante Entwicklungsphasen und Meilensteine. Stand: **v1.5.3** (Alpha).

Status-Legende:

| Symbol | Bedeutung |
|--------|-----------|
| ✅ | Fertig / stabil |
| 🔄 | In Arbeit / teilweise |
| 📋 | Geplant |
| 💡 | Idee / Backlog |

**Epics → Tickets:** Epics werden nicht direkt implementiert. Siehe Ticket-Workflow in [CONTRIBUTING.md](CONTRIBUTING.md).

---

## Phase 0 — Foundation ✅

| Item | Status |
|------|--------|
| Flask + SQLite + Jinja2 | ✅ |
| Installer (`scripts/install.py`) | ✅ |
| Environment & Config Guards | ✅ |
| SQL-Migrationen (`006`–`032`) | ✅ |
| Health Endpoint (`/health`) | ✅ |
| Docker + Gunicorn Deployment | ✅ |
| DB-Abstraction (`game/db.py`) | ✅ |
| Bootstrap & Migration Guard | ✅ |
| pytest-Suite (**513 Tests**) | ✅ |

---

## Phase 1 — Economy Core ✅

| Item | Status |
|------|--------|
| Auth (Register/Login/Logout) | ✅ |
| E-Mail-Verifikation & Passwort-Reset | ✅ |
| Ressourcen-Tick (Ferronit, Crytite, Brennzellen) | ✅ |
| Energie-System + EffectResolver | ✅ |
| Gebäude bauen / upgraden | ✅ |
| Bau-Queue mit Limit | ✅ |
| Account-Forschung + Queue | ✅ |
| Tech-Tree Visualisierung | ✅ |
| Ranking & Player Scores | ✅ |
| SPA/PJAX Navigation | ✅ |
| Live-Polling + rAF Queue-UI | ✅ |
| Idempotente Build/Research APIs | ✅ |
| Queue-Engine (zentral) | ✅ |
| Race-safe Queue Tests | ✅ |

Docs: [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md), [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md), [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md)

---

## Phase 2 — Operations & Admin ✅

| Item | Status |
|------|--------|
| Admin Control Center | ✅ |
| Admin JSON API (`/api/admin/*`) | ✅ |
| Audit Log | ✅ |
| Queue-Management (cancel, finish-due, clear) | ✅ |
| Player/Planet-Tools | ✅ |
| Balance Editor (`admin_balance`) | ✅ |
| Legacy Admin Forms (parallel) | ✅ |
| MOTD & Universe Settings | ✅ |
| Ban-System | ✅ |
| Support-Tickets (Spieler + Admin) | ✅ |

---

## Phase 3 — Multi-Kolonie & Planet Evolution ✅

| Item | Status |
|------|--------|
| Planet Scope (`active_planet_id`) | ✅ |
| Header Planet Switcher | ✅ |
| Kolonisierung (Fleet + API) | ✅ |
| Planet Evolution (DNA, Traits, Level) | ✅ |
| Planet-Forschung (separat von Account-Tech) | ✅ |
| Specialization, Policies, Events | ✅ |
| Trade Routes / Economy Chains | ✅ |
| Planet löschen (Non-Homeworld) | ✅ |

Docs: [PLANET_SCOPE.md](PLANET_SCOPE.md), [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)

---

## Phase 4 — Military & Expansion 🔄

| Item | Status | Notizen |
|------|--------|---------|
| **Galaxie** — Karte, Slots, Koordinaten | ✅ | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| **Werft** — Schiffsbau, Queue, fuel_cells | ✅ | `orbital_shipyard` |
| **Flotte** — Send, Tick, Missionen | ✅ | Attack combat active |
| **Trader Hub** — Unified Exchange, Scrapyard | ✅ | GC-402 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Verteidigung** — Türme, Schilder, Queue, Ranking | ✅ | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) |
| **Kampf-Auflösung** — Resolver, Reports, Loot, Debris, Ranking | ✅ | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md); `test_combat.py` |
| **GC-700** — Combat polish / gaps (kein Resolver-Neubau) | 📋 | Siehe [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) § GC-700 Readiness |
| Fleet Logistics (collect/distribute) | 📋 | `logistics_not_implemented` in `fleet.py` → GC-900 |
| Recycler-Mission | ✅ | GC-800A Backend + GC-800B UI; GC-800C UX optional |
| Espionage (beyond probe report) | ✅ | GC-401 tiered intel + inbox UI |
| Expedition event engine | ✅ | GC-402 weighted events + structured metadata |
| Expedition fleet mission feedback | ✅ | GC-402B preview hints, status, auto-position 16 |
| Expedition report visual upgrade | ✅ | GC-402C sci-fi event-card inbox UI |

Docs: [FLEET_SYSTEM.md](FLEET_SYSTEM.md), [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)

Empfohlene Reihenfolge (verbleibend — nach [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)):

```
GC-800C Recycler UX (optional) → GC-900 Fleet Logistics → GC-700 Combat polish (nur Lücken)
```

---

## Phase 5 — Social & Meta 🔄

| Item | Status | Notizen |
|------|--------|---------|
| **PlayerCard** — Profil, Stats | ✅ | `/api/player-card/*` |
| **Messages** — Inbox, Send | ✅ | Flotten-/System-Mails |
| **Chat** — Rooms, DM, Alliance room | ✅ | Rate limit in-process |
| Chat Admin (mute, ban, delete) | ✅ | |
| **Allianz** — Hub UI | 🔄 | `alliance.py` minimal; `/alliance` teils UI |
| Allianz Gründung / Rechte / Diplomatie | 📋 | |
| **Ranking** — Live API | ✅ | |
| Marketplace (Spieler-Handel) | 💡 | |

---

## Phase 6 — Security Hardening 📋

Vor öffentlichem Production-Launch.

| Item | Priorität | Status |
|------|-----------|--------|
| Passwort-KDF (bcrypt/argon2) | P0 | 📋 |
| Rate-Limiting Login/Register | P0 | 📋 |
| Session-Cookie Flags | P1 | 📋 |
| CSRF HTML-Forms | P1 | 📋 |
| Security-Headers | P2 | 📋 |

Details: [SECURITY.md](SECURITY.md)

---

## Phase 7 — Platform & Scale 📋

| Item | Status | Notizen |
|------|--------|--------|
| PostgreSQL Backend | 📋 | Hooks in `game/db.py` |
| Multi-Worker / horizontale Skalierung | 📋 | Benötigt Postgres + Locks |
| Redis Sessions/Cache/Chat rate limit | 💡 | |
| WebSocket Push (optional) | 💡 | Polling bleibt Fallback |
| i18n UI-Switch (DE/EN) | 🔄 | `game/i18n.py`, `en.json`; Default `de` |
| CDN / Asset-Pipeline | 💡 | `VERSION` Cache-Bust |

---

## Phase 8 — Polish & Live Ops 💡

| Item | Status |
|------|--------|
| Balancing-Tooling (Admin) | 🔄 teilweise |
| Tutorial / Onboarding | 💡 |
| Season / Universe-Reset | 💡 |
| CI Pipeline | 💡 |
| Automated Backups | 📋 Operator-intern |

---

## Meilenstein-Übersicht

```
2025 Q1–Q2   Phase 0–2 ✅   Foundation, Economy, Admin
2025 Q3–Q4   Phase 3–4 🔄   Multi-Kolonie, Galaxy, Fleet
2026 Q1      Phase 4b 🔄     Defense ✅; Combat ✅
2026 Q2      Phase 5–6       Alliance polish, Security, Scale
```

*Timeline orientierend — keine festen Release-Daten.*

---

## Technische Schulden (bekannt)

| Thema | Impact | Ziel |
|-------|--------|------|
| SHA-256 Passwörter | Security | Phase 6 |
| Kein Rate-Limiting (Login) | Abuse | Phase 6 |
| Chat rate limit in-process | Multi-worker | Redis |
| Recycler mission (debris harvest) | Gameplay | Phase 4b |
| Legacy Admin Forms doppelt | Wartung | Cleanup |
| SQLite Single-Writer | Scale | Phase 7 |
| README vs VERSION drift | Docs | README auf 1.5.3 |
| `fleet_presets` CHECK ohne colonize | Schema | Migration fix |

---

## Epic → Ticket Mapping (Beispiele)

| Epic | Beispiel-Tickets |
|------|------------------|
| EPIC-02 Fleet | GC-301 Planet Scope Sync, GC-302 Preview origin |
| EPIC-03 Galaxy | GC-310 Live slot API client |
| EPIC-04 Economy | GC-320 Fuel bar sync |
| EPIC-05 Planet Evolution | GC-330 Policy cooldown UI |

---

## Priorisierung

1. **Spieler-sichtbarer Wert** — Mechanik vor Refactor
2. **Security vor Public Beta** — Phase 6 blockiert Launch
3. **Kanonische Systeme** — kein Parallel-Build (siehe [ARCHITECTURE.md](ARCHITECTURE.md))
4. **GC-000 Enforcement** — [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md); CI-Check `test_core_architecture_enforcement.py`
5. **Tests mitliefern** — jede Queue/DB-Änderung braucht pytest

### Architektur-Schulden (GC-000 Follow-ups)

| Item | Status |
|------|--------|
| **GC-510** — Build/Research cancel → Restqueue `recalculate` | ✅ |
| **GC-512** — Queue static contract + [Queue Manual QA](GC-512_QUEUE_MANUAL_QA.md) | ✅ |
| **GC-512** — [Architecture Validation Pass](GC-512_ARCHITECTURE_VALIDATION.md) (alle Module) | ✅ |
| **GC-513** — Windows parallel build race test (timeout + mutex recovery) | ✅ |
| **GC-600** — Defense Phase 1 (Queue, Scope, `applyActionState`, pytest) | ✅ |
| **GC-601** — [Project Inventory](PROJECT_INVENTORY.md) + Docs/Roadmap Reality Sync | ✅ |
| Admin Control Center auf PJAX/State (statt `reload`) | 💡 |
| GC-000 v2 — Regeln 15–17 (Parallel Systems, Duplicate Math, Owners) | ✅ |

### Tech debt (pytest, nicht blockierend)

| Item | Notizen |
|------|---------|
| `test_messages_js_spy_report_and_category_label` | `renderSpyReport` nach Inbox-Refactor umbenannt/entfernt — Test anpassen |
| `test_no_undocumented_location_reload_in_game_static` | `main.js:684` PJAX-Fallback — Allowlist oder `GC.reloadCurrentPage` only |

---

## Verwandte Dokumente

- [ARCHITECTURE.md](ARCHITECTURE.md) — Systemübersicht
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle Tests
- [SECURITY.md](SECURITY.md) — Phase 6 Details
- [CONTRIBUTING.md](CONTRIBUTING.md) — Ticket-Workflow
