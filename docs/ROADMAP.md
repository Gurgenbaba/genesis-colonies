# Genesis Colonies — Roadmap

Geplante Entwicklungsphasen und Meilensteine. Stand: **v1.5.9.2** (Alpha, Reality-Sync 2026-06-24).

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
| SQL-Migrationen (`006`–`076`) | ✅ |
| Health Endpoint (`/health`) | ✅ |
| Docker + Gunicorn Deployment | ✅ |
| DB-Abstraction (`game/db.py`) | ✅ |
| Bootstrap & Migration Guard | ✅ |
| pytest-Suite (**2165** Tests) | ✅ |

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
| **Auktionshaus** — Lootbox-Auktionen (keine Eventboxen) | ✅ | GC-550 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — TopG Postback + 12h Belohnung | ✅ | GC-551 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Multi-Provider (TopG, GameToor) | ✅ | GC-552 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — GTop100 Pingback Provider | ✅ | GC-553 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Arena-Top100 (Link only) | ✅ | GC-554 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Arena-Top100 Postback + reset Cooldown | ✅ | GC-555 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — GameToor IVN Auto-Rewards | ✅ | GC-556 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Verteidigung** — Türme, Schilder, Queue, Ranking | ✅ | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) |
| **Kampf-Auflösung** — Resolver, Reports, Loot, Debris, Ranking | ✅ | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md); `test_combat.py` |
| **GC-700** — Combat polish / gaps (kein Resolver-Neubau) | 📋 | Siehe [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) § GC-700 Readiness |
| Fleet Logistics (collect/distribute) | ✅ | GC-526–531: Bulk API, `/logistics` UI, Reports (`report_phase`) — [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Recycler-Mission | ✅ | GC-800A Backend + GC-800B UI; GC-800C UX optional |
| Espionage (beyond probe report) | ✅ | GC-401 tiered intel + inbox UI |
| Expedition event engine | ✅ | GC-402 weighted events + structured metadata |
| Expedition fleet mission feedback | ✅ | GC-402B preview hints, status, auto-position 16 |
| Expedition report visual upgrade | ✅ | GC-402C sci-fi event-card inbox UI |

Docs: [FLEET_SYSTEM.md](FLEET_SYSTEM.md), [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)

Empfohlene Reihenfolge (verbleibend — nach [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)):

```
GC-803 ✅ → GC-900A–900E / GC-526–531 Logistics ✅ → GC-806 Navigation Shell ✅ → GC-700 Combat polish
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
| Passwort-KDF (argon2id) | P0 | ✅ GC-SEC-P0 |
| Rate-Limiting Login/Register | P0 | ✅ GC-SEC-P0 |
| Session-Cookie Flags | P1 | ✅ GC-SEC-P0 |
| CSRF HTML-Forms (Auth) | P1 | ✅ GC-SEC-P0 |
| Security Headers | P2 | ✅ GC-SEC-P0 |
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

## Phase 9 — Imperium & Expansion (Genesis 2.0) 📋

Langfristige Vision: Planet Evolution als zentrales Fortschrittssystem, Command Map als Empire Screen. **Kein Neubau** — Erweiterung auf Planet Scope, Galaxy, Fleet und Planet Evolution.

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Epic: **EPIC-15**

| Ticket | Fokus | Status |
|--------|-------|--------|
| **GC-560** | Empire Identity Layer — [Spec](GC-560_EMPIRE_IDENTITY_LAYER.md) | 📋 |
| **GC-561** | Colony Roles Extended (PlayerCard, Surfaces) | 📋 |
| **GC-562** | Evolution Unlock Gates — Level → Expansion Sites ([Spec](GC-562_EVOLUTION_UNLOCK_GATES.md)) | ✅ |
| **GC-562A** | Expansion Gates Polish ([Spec](GC-562A_EXPANSION_GATES_POLISH.md)) | ✅ |
| **GC-563** | Command Map MVP — Hub-and-Spoke Graph ([Spec](GC-563_COMMAND_MAP_MVP.md)) | ✅ |
| **GC-563B** | Command Map Viewport — Pan & Zoom ([Spec](GC-563B_COMMAND_MAP_VIEWPORT.md)) | ✅ |
| **GC-564** | Regions & Sectors — Panel-Bänder + Teaser-Sites ([Spec](GC-564_REGIONS_SECTORS.md)) | ✅ |
| **GC-564B** | Spatial Command Map — Nebel + freie Knoten ([Spec](GC-564B_SPATIAL_COMMAND_MAP.md)) | ✅ |
| **GC-565** | Chokepoints — Gate-Knoten zwischen Regionen ([Spec](GC-565_CHOKEPOINTS.md)) | ✅ |
| **GC-566** | Influence Layer — Eigenreich-Territorium ([Spec](GC-566_INFLUENCE_LAYER.md)) | ✅ |
| **GC-567** | Expansion Sites v2 — Orte mit Versprechen & Inspector ([Spec](GC-567_EXPANSION_SITES_V2.md)) | ✅ |
| **GC-567B** | Region Landmarks ([Spec](GC-567B_REGION_LANDMARKS.md)) | ✅ |
| **GC-570** | World Map + Role Actions ([Spec](GC-570_WORLD_MAP_DIRECTION.md)) | ✅ |
| **GC-580B** | Viewport-aware Sector Loading | ✅ |
| **GC-580C** | Infinite Map Background Tiling | ✅ |
| **GC-581** | Strategic Worlds (Presentation) ([Spec](GC-581_STRATEGIC_WORLDS.md)) | ✅ |
| **GC-582** | Dynamic Colonization ([Spec](GC-582_DYNAMIC_COLONIZATION.md)) | ✅ 582A–582D + [582F UX](GC-582F_COLONIZATION_UX_POLISH.md) |
| **GC-583** | Expedition Worlds ([Spec](GC-583_EXPEDITION_WORLDS.md)) | ✅ 583A–583C |
| **GC-566B** | Dynamic Influence ([Spec](GC-566B_DYNAMIC_INFLUENCE.md)) | 📋 Spec |
| **GC-571** | Shared World Presence ([Spec](GC-571_SHARED_WORLD_PRESENCE.md)) | 📋 Spec |
| **GC-597D/E** | Command Map DEV Preview + Foreign Node Fallback | ✅ |
| **GC-620B** | Locale Reality Sync ([Spec](GC-620B_LOCALE_REALITY_SYNC.md)) | ✅ |
| **GC-SEC-P0** | KDF, Rate Limits, Security Headers | ✅ |
| **GC-599A** | Foreign Empire Presence — Map glaubwürdig bewohnt ([Spec](GC-599A_FOREIGN_EMPIRE_PRESENCE.md)) | ✅ |
| **GC-598** | Mission Actions im World Inspector | 📋 Next |
| **GC-599** | Foreign Worlds / Enemy Nodes vollständig | 📋 |
| **GC-569** | ~~Presence Overlay~~ → siehe GC-571 | 📋 superseded |
| **GC-568** | Territorial Warfare | 📋 |

Start nach Completion-First-Pass (GC-610), sofern nicht reine Identity-Tickets (560–561) parallel.

---

## Meilenstein-Übersicht

```
2025 Q1–Q2   Phase 0–2 ✅   Foundation, Economy, Admin
2025 Q3–Q4   Phase 3–4 🔄   Multi-Kolonie, Galaxy, Fleet
2026 Q1      Phase 4b 🔄     Defense ✅; Combat ✅
2026 Q2      Phase 5–6       Alliance polish, Security, Scale
2026 Q3+     Phase 9         Imperium & Expansion (EPIC-15, GC-560+)
```

*Timeline orientierend — keine festen Release-Daten.*

---

## Technische Schulden (bekannt)

| Thema | Impact | Ziel |
|-------|--------|------|
| SHA-256 Passwörter (Legacy) | Security | Migriert bei Login (GC-SEC-P0) |
| Kein Rate-Limiting (Login) | Abuse | ✅ GC-SEC-P0 |
| Chat rate limit in-process | Multi-worker | Redis |
| Recycler UX polish (GC-800C) | Optional UX | GC-800A/B ✅ — [GC-800_RECYCLER.md](GC-800_RECYCLER.md) |
| Legacy Admin Forms doppelt | Wartung | Cleanup |
| SQLite Single-Writer | Scale | Phase 7 |
| README vs VERSION drift | Docs | README auf 1.5.3 |
| `fleet_presets` CHECK ohne colonize | Schema | Migration fix |
| Ressourcen als REAL statt INTEGER | Präzision ab ~9×10¹⁵ | [GC-622B](GC-622B_RESOURCE_INTEGER_MIGRATION.md) (Backlog) |

---

## Epic → Ticket Mapping (Beispiele)

| Epic | Beispiel-Tickets |
|------|------------------|
| EPIC-02 Fleet | GC-301 Planet Scope Sync, GC-302 Preview origin |
| EPIC-03 Galaxy | GC-310 Live slot API client |
| EPIC-04 Economy | GC-320 Fuel bar sync |
| EPIC-05 Planet Evolution | GC-330 Policy cooldown UI |
| EPIC-15 Imperium & Expansion | GC-560 Empire Identity → GC-568 Territorial Warfare |

---

## Priorisierung

### Completion-First (Alpha — ab GC-600)

Vor neuen Features: **vorhandene Kernsysteme auf 100 %** — messbar via [GC-610](GC-610_COMPLETE_DEFINITION_AUDIT.md) (DoC + Reifegrade). Strategie: [GC-600](GC-600_PROJECT_GAP_ANALYSIS.md) § Completion-First.

**Nächste Tickets (Reihenfolge — siehe [GC-610](GC-610_COMPLETE_DEFINITION_AUDIT.md)):**

1. GC-610 Definition of Complete ✅ → 2. GC-545 Browser Audit ✅ → 3. GC-546D–A Poll/Live-State ✅ → 4. **GC-547/547B** GPU Idle ✅ (Abnahme: FPS-Messung) → 5. **GC-611** Fleet Close-Out → … → 615 → **GC-536A–E** Queue Card UX

**Performance-Gate:** FPS idle ≈ 0–1 → GC-547/547B schließen, weiter GC-611. FPS 144+ idle → [GC-547C](GC-547C_FPS_COMPOSITOR_AUDIT.md) vor Fleet Close-Out.

### Allgemeine Regeln

1. **Vollenden vor Erweitern** — Tier 1 QA vor Tier 3 Greenfield (Marketplace, Radar, Seasons)
2. **Spieler-sichtbarer Wert** — Mechanik vor Refactor
3. **Security vor Public Beta** — Phase 6 blockiert Launch (nach Completion-Pass)
4. **Kanonische Systeme** — kein Parallel-Build (siehe [ARCHITECTURE.md](ARCHITECTURE.md))
5. **GC-000 Enforcement** — [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md); CI-Check `test_core_architecture_enforcement.py`
6. **Tests mitliefern** — jede Queue/DB-Änderung braucht pytest

### Architektur-Schulden (GC-000 Follow-ups)

| Item | Status |
|------|--------|
| **GC-510** — Build/Research cancel → Restqueue `recalculate` | ✅ |
| **GC-512** — Queue static contract + [Queue Manual QA](GC-512_QUEUE_MANUAL_QA.md) | ✅ |
| **GC-512** — [Architecture Validation Pass](GC-512_ARCHITECTURE_VALIDATION.md) (alle Module) | ✅ |
| **GC-513** — Windows parallel build race test (timeout + mutex recovery) | ✅ |
| **GC-600** — Defense Phase 1 (Queue, Scope, `applyActionState`, pytest) | ✅ |
| **GC-601** — [Project Inventory](PROJECT_INVENTORY.md) + Docs/Roadmap Reality Sync | ✅ |
| **GC-601B** — [Documentation Consistency Sync](GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md) (Defense, Recycler, GC-600) | ✅ |
| **GC-610** — [Complete Definition Audit](GC-610_COMPLETE_DEFINITION_AUDIT.md) (DoC, Reifegrade) | ✅ |
| **GC-545** — [Live-State Browser Audit](GC-545_LIVE_STATE_BROWSER_AUDIT.md) | ✅ |
| **GC-546** — [Live-State Fixes](GC-546_LIVE_STATE_FIXES.md) (546D→A) | ✅ |
| **GC-547** — [GPU Performance Audit](GC-547_GPU_PERFORMANCE_AUDIT.md) + [547B](GC-547B_LANDING_LOGIN_GPU_AUDIT.md) | ✅ (FPS-Abnahme) |
| **GC-547C** — [FPS / Compositor Audit](GC-547C_FPS_COMPOSITOR_AUDIT.md) | ✅ (FPS remessen) |
| **GC-801** — Resource bar + buildings panel action-state sync | ✅ |
| **GC-802** — Fleet timer, galaxy prefill, planet-switch lifecycle | ✅ |
| **GC-803** — Fleet preset & mass expedition test stabilization (`IntegrityError`) | ✅ |
| **GC-804** — Sidebar accordion state persistence (PJAX) | ✅ |
| **GC-805** — Desktop sidebar sticky scroll | ✅ |
| **GC-806** — Navigation Shell dual-sidebar + bottom dock (806A–806D) | ✅ | [ARCHITECTURE.md](ARCHITECTURE.md) § Navigation Shell |
| **GC-900A** — Logistics spec + Option A ([GC-900_LOGISTICS.md](GC-900_LOGISTICS.md)) | ✅ |
| **GC-900B** — Collect backend (`collect` mission + batch orchestration) | ✅ |
| **GC-900C** — Collect UI | ✅ |
| **GC-900D** — Distribute backend (`transport` + batch orchestration) | ✅ |
| **GC-900E** — Distribute UI / polish | ✅ |
| **GC-526–531** — Logistics bulk, routes, UI, inbox reports, QA docs | ✅ |
| Admin Control Center auf PJAX/State (statt `reload`) | 💡 |
| GC-000 v2 — Regeln 15–17 (Parallel Systems, Duplicate Math, Owners) | ✅ |
| **GC-536** — [Queue Card UX](GC-536_QUEUE_CARD_UX.md) (536A–F ✅) | ✅ |
| **GC-557** — [Megabunker UX Feedback Polish](GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md) (557A–F) | 📋 |
| **GC-622** — [Integer Overflow Audit](GC-622_INTEGER_OVERFLOW_AUDIT.md) (INT32-Risiko geschlossen) | ✅ |
| **GC-622B** — [Resource INTEGER Migration](GC-622B_RESOURCE_INTEGER_MIGRATION.md) | 💡 |

### Tech debt (pytest, nicht blockierend)

| Item | Notizen |
|------|---------|
| `test_messages_js_spy_report_and_category_label` | `renderSpyReport` nach Inbox-Refactor umbenannt/entfernt — Test anpassen |
| `test_no_undocumented_location_reload_in_game_static` | `main.js:684` PJAX-Fallback — Allowlist oder `GC.reloadCurrentPage` only |

---

## Verwandte Dokumente

- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Genesis 2.0 Design Manifest (EPIC-15)
- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md) — Definition of Complete / Reifegrade
- [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md) — Strategisches Gap-Audit
- [GC-622_INTEGER_OVERFLOW_AUDIT.md](GC-622_INTEGER_OVERFLOW_AUDIT.md) — INT32/Overflow Tech-Audit ✅
- [ARCHITECTURE.md](ARCHITECTURE.md) — Systemübersicht
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle Tests
- [SECURITY.md](SECURITY.md) — Phase 6 Details
- [CONTRIBUTING.md](CONTRIBUTING.md) — Ticket-Workflow
