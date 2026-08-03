# Genesis Colonies — Roadmap

Geplante Entwicklungsphasen und Meilensteine. Stand: **v0.9 Alpha** / Build `0.5.9.83` (Reality-Sync 2026-08-01).

Status-Legende:

| Symbol | Bedeutung |
|--------|-----------|
| ✅ | Fertig / stabil |
| 🔄 | In Arbeit / teilweise |
| 📋 | Geplant |
| 💡 | Idee / Backlog |

**Epics → Tickets:** Epics werden nicht direkt implementiert. Siehe Ticket-Workflow in [CONTRIBUTING.md](CONTRIBUTING.md).

**Beta Gate:** Der Übergang von Alpha zu Beta ist verbindlich in [BETA_GATE.md](BETA_GATE.md) geregelt. `v1.0.0-beta.1` ist erst erlaubt, wenn Alliance MVP, GC-BETA-001, GC-BETA-002 und GC-BETA-003 abgeschlossen sind.

---

## Phase 0 — Foundation ✅

| Item | Status |
|------|--------|
| Flask + SQLite + Jinja2 | ✅ |
| Installer (`scripts/install.py`) | ✅ |
| Environment & Config Guards | ✅ |
| SQL-Migrationen (`006`–`124`) | ✅ |
| Health Endpoint (`/health`) | ✅ |
| Docker + Gunicorn Deployment | ✅ |
| DB-Abstraction (`game/db.py`) | ✅ |
| Bootstrap & Migration Guard | ✅ |
| pytest-Suite (**4219** Tests) | ✅ |

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
| **Lootbox Meta-only Rebalance** | ✅ | GC-864 — keine Economy-Inflation aus Containern |
| **Collector Exchange** — Sammler-Markt, 4 Spezialisten, Prestige | 🔄 | EPIC-18 · GC-965A/B ✅ · GC-966A/B ✅ UI · GC-967 Inventar-Hints 📋 |
| **Auktionshaus** — Lootbox-Auktionen (keine Eventboxen) | ✅ | GC-550 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — TopG Postback + 12h Belohnung | ✅ | GC-551 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Multi-Provider (TopG, GameToor) | ✅ | GC-552 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — GTop100 Pingback Provider | ✅ | GC-553 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Arena-Top100 (Link only) | ✅ | GC-554 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — Arena-Top100 Postback + reset Cooldown | ✅ | GC-555 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Vote Center** — GameToor IVN Auto-Rewards | ✅ | GC-556 [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| **Verteidigung** — Türme, Schilder, Queue, Ranking | ✅ | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) |
| **Kampf-Auflösung** — Resolver, Reports, Loot, Debris, Ranking | ✅ | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md); `test_combat.py` |
| **GC-700A** — Combat simulator (`/combat-simulator`, Monte-Carlo) | ✅ | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) § GC-700A |
| **GC-700B** — Smart import (auto-fill + spy reports) | ✅ | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) § GC-700A |
| **GC-700** — Combat polish / gaps (kein Resolver-Neubau) | ✅ GC-700E | Report-UX residual: CTAs, empty loot, kind badges — [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| **Combat Encounter Theater** — face-off before report | ✅ | GC-CT-001…005 — [COMBAT_THEATER.md](COMBAT_THEATER.md) |
| Fleet Logistics (collect/distribute) | ✅ | GC-526–531: Bulk API, `/logistics` UI, Reports (`report_phase`) — [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Recycler-Mission | ✅ | GC-800A Backend + GC-800B UI; GC-800C UX optional |
| Espionage (beyond probe report) | ✅ | GC-401 tiered intel + inbox UI |
| Expedition event engine | ✅ | GC-402 + GC-620I/J + GC-EXPO-W1/DIR/J-B (weights ~60% loot, directives, compression, Lost Colony / Rogue AI) |
| Expedition fleet mission feedback | ✅ | GC-402B + GC-EXPO-UX preview rating / mass slots |
| Expedition report visual upgrade | ✅ | GC-402C + GC-EXPO-UX transparency |

Docs: [FLEET_SYSTEM.md](FLEET_SYSTEM.md), [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)

Empfohlene Reihenfolge (verbleibend — nach [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)):

```
GC-803 ✅ → GC-900A–900E / GC-526–531 Logistics ✅ → GC-806 Navigation Shell ✅ → GC-700 Combat polish
```

---

## Phase 5 — Social & Meta ✅ (Alliance MVP)

| Item | Status | Notizen |
|------|--------|---------|
| **PlayerCard** — Profil, Stats | ✅ | `/api/player-card/*` |
| **Messages** — Inbox, Send | ✅ | Flotten-/System-Mails |
| **Chat** — Rooms, DM, Alliance room | ✅ | Rate limit in-process |
| Chat Admin (mute, ban, delete) | ✅ | |
| **Allianz** — Hub UI (EPIC-09 MVP) | ✅ | GC-AL-MVP-01…09: Management, Spenden, Projekte, Tech, Boni, PJAX |
| Allianz Diplomatie → Fleet Hooks | ✅ | GC-AL-DIP-01: NAP-Lock, Bündnis-Transport, war-Flag |
| Allianz Combat-/Kriegs-Meta | 📋 | Report-Badges, Score, End-War UI (nach DIP-01) |
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

Details: [SECURITY.md](SECURITY.md)

---

## Phase 7 — Platform & Scale 📋

Master-Doc: **[GC_PERF_CORE.md](GC_PERF_CORE.md)** (EPIC Performance Core).  
**Produktentscheidung (2026-07):** Produktion bleibt auf **SQLite**. Postgres-Schema/Driver-Arbeit bleibt optionaler Code-Pfad; **Cutover / Multi-Worker auf PG sind nicht geplant.** Scale = Ops-Disziplin (1 Replica, 1 Worker, Sidecar, Backups) — [CAPABILITY_STATUS.md](CAPABILITY_STATUS.md), [RAILWAY_OPERATOR.md](RAILWAY_OPERATOR.md).

| Item | Status | Notizen |
|------|--------|--------|
| Performance Core Epic | ✅ Foundation | SQLite-first; PG-Cutover **deferred / not planned** |
| Messbarkeit (GC-PERF-CORE-001) | ✅ | Request-/SQL-/Payload-Budgets auf RequestPerf |
| PostgreSQL Backend (Driver/Pool) | ✅ optional | Code vorhanden; **nicht** Produktionsziel |
| PostgreSQL Schema-Port | ✅ optional | Historisch; kein Cutover-Plan |
| PostgreSQL Backend-Parität / Staging / Cutover | 💡 deferred | Bewusst nicht priorisiert — SQLite bleibt |
| Multi-Worker / Game-Worker | 💡 deferred | Erst sinnvoll mit Multi-Writer-DB; unter SQLite = 1 Worker |
| Diet/Delta State | ✅ | `poll_version` + `?since=` |
| Lazy Resource Accrual | ✅ | `GC_RESOURCE_PERSIST_SEC` (default 600) |
| `main.js` Modularisierung | 🔄 Scaffold | Echter Split → GC-PERF-JS-002 |
| Redis / Definition Cache | ✅ Basis | EffectResolver-Cache → GC-PERF-EFFECT-CACHE-001 |
| Lasttest-Werkzeug | ✅ | `scripts/perf_load_test.py` — Staging-Baseline später |
| WebSocket Push (optional) | 💡 | Polling bleibt Fallback |
| i18n UI-Switch (DE/EN) | 🔄 | `game/i18n.py`, Locales; Default `de` — siehe CAPABILITY P1 |
| CDN / Asset-Pipeline | 💡 | `VERSION` Cache-Bust |
| SQLite Ops Hygiene | 🔄 | 1 Worker/Replica, embedded cron, daily backups |

---

## Phase 8 — Polish & Live Ops 💡

| Item | Status |
|------|--------|
| Balancing-Tooling (Admin) | 🔄 teilweise |
| Tutorial / Onboarding | 💡 |
| Season / Universe-Reset | 💡 |
| **World Boss Events (EPIC-20)** | 🔄 | GC-W01…W08 + GC-WB-TAME — [WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) |
| **Pirate Ecosystem (EPIC-21)** | ✅ | GC-P00…P18 ship-gate — [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md) |
| **LiveOps Retention (EPIC-22)** | ✅ | Login calendar + Battle Pass — [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) |
| **Payment / Shop (EPIC-23)** | ✅ | Stripe + PayPal convenience shop — [PAYMENT_SHOP.md](PAYMENT_SHOP.md) |
| **Commander Classes (EPIC-27)** | 🔄 | 5 Klassen, linearer Skill-Trunk, TK-Swap — [COMMANDER_CLASSES.md](COMMANDER_CLASSES.md) |
| CI Pipeline | 💡 |
| Automated Backups | 📋 Operator-intern |

---

## Phase 9 — Imperium & Expansion (Genesis 2.0) 📋

Langfristige Vision: Planet Evolution als zentrales Fortschrittssystem, Command Map als Empire Screen. **Kein Neubau** — Erweiterung auf Planet Scope, Galaxy, Fleet und Planet Evolution.

Design Manifest: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · Epic: **EPIC-15**

| Ticket | Fokus | Status |
|--------|-------|--------|
| **GC-560** | Empire Identity Layer — [Spec](GC-560_EMPIRE_IDENTITY_LAYER.md) | ✅ |
| **GC-575** | Planet Registry — Imperiumsübersicht rechts — [Spec](GC_PLANET_REGISTRY.md) | ✅ 575A MVP |
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
| **GC-593** | World Map De-Scope — klassische Galaxie wieder Hauptflow; Command Map Dev-Preview only | ✅ 593A–C |
| **GC-570** | World Map + Role Actions ([Spec](GC-570_WORLD_MAP_DIRECTION.md)) — **de-scoped** (Dev-Preview) | ✅ legacy |
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
| **GC-598** | Mission Actions im World Inspector | 📋 paused (Dev-Preview only) |
| **GC-599** | Foreign Worlds / Enemy Nodes vollständig | 📋 paused |
| **GC-569** | ~~Presence Overlay~~ → siehe GC-571 | 📋 superseded |
| **GC-568** | Territorial Warfare | 📋 |

Start nach Completion-First-Pass (GC-610), sofern nicht reine Identity-Tickets (560–561) parallel.

---

## Meilenstein-Übersicht

```
2025 Q1–Q2   Phase 0–2 ✅   Foundation, Economy, Admin
2025 Q3–Q4   Phase 3–4 🔄   Multi-Kolonie, Galaxy, Fleet
2026 Q1      Phase 4b 🔄     Defense ✅; Combat ✅
2026 Q2      Phase 5–6       Alliance MVP ✅, Beta Gate, Security
2026 Q3+     Phase 9         Imperium & Expansion (EPIC-15, GC-560+)
```

*Timeline orientierend — keine festen Release-Daten.*

---

## Beta Gate & Versionsstrategie

Genesis Colonies bleibt `v0.9.x` Alpha, bis alle Alpha-Exit-Gates aus [BETA_GATE.md](BETA_GATE.md) bestanden sind:

| Gate | Ziel |
|------|------|
| Alliance MVP | ✅ Abgeschlossen (GC-AL-MVP-01…09) — Hub, Bewerbungen, Spenden, Projekte, Tech, Boni, PJAX; Deep-Hooks später |
| GC-BETA-001 — Architecture & CI Green | Architektur- und PJAX-Regressionstests grün; keine neuen Reload-/Href-Verstöße |
| GC-BETA-002 — Documentation Reality Sync | Master-Docs spiegeln den Code-Stand wider |
| GC-BETA-003 — Alpha Exit Validation | Manueller Smoke-Test aller Kernsysteme ohne P0/P1-Fund |

Versionsbedeutung:

| Version | Bedeutung |
|---------|-----------|
| `0.9.x` | Alpha — Grundsysteme entstehen noch |
| `1.0.0-beta.x` | Core Architecture Freeze; Fokus auf Stabilität, Balancing, UX, Performance und Community-Feedback |
| `1.0.0` | Offizieller Release |
| `1.0.x` | Bugfixes, Performance, kleine Quality-of-Life-Verbesserungen |
| `1.1.x` | Neue Features auf bestehender Architektur |
| `2.0` | Fundamentale Architektur- oder Designänderungen mit bewusstem Migrationspfad |

Wartungs-Schulden sind kein Beta-Blocker, solange GC-000 eingehalten wird, CI grün ist, keine P0/P1 offen sind und die Schulden dokumentiert sind.

---

## Technische Schulden (bekannt)

| Thema | Impact | Ziel |
|-------|--------|------|
| SHA-256 Passwörter (Legacy) | Security | Migriert bei Login (GC-SEC-P0) |
| Kein Rate-Limiting (Login) | Abuse | ✅ GC-SEC-P0 |
| Chat rate limit in-process | Multi-worker | Redis |
| Recycler UX polish (GC-800C) | Optional UX | GC-800A/B ✅ — [GC-800_RECYCLER.md](GC-800_RECYCLER.md) |
| Legacy Admin Forms doppelt | Wartung | Cleanup |
| SQLite Single-Writer | Scale | Ops: 1 Worker/Replica — Cutover **nicht** geplant ([CAPABILITY_STATUS.md](CAPABILITY_STATUS.md)) |
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

### Capability-Prioritäten (aktuell)

Kanonisch: **[CAPABILITY_STATUS.md](CAPABILITY_STATUS.md)**. Kurz:

| Prio | Fokus | Status |
|------|-------|--------|
| P0 | Combat polish (GC-700E) → dann P2 | ✅ GC-700E; GC-AL-DIP-01 ✅ |
| P1 | Beta Gate, First-30, Collector, Megabunker, i18n | 💡 zurückgestellt |
| P2 | Alliance Kriegs-Meta · Imperium Presence (566B/568) · Marketplace | 📋 aktiv |
| P3 | Radar, Seasons, Contract-Schuld (GC-512D, …) | 💡 |

**Nicht priorisieren:** Postgres-Cutover, WebSocket, parallele Engines.

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
7. **Beta Gate** — `v1.0.0-beta.1` nur nach [BETA_GATE.md](BETA_GATE.md); ab Beta gilt Core Architecture Freeze

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
| Admin Control Center auf PJAX/State (statt `reload`) | 💡 deferred — Hard-Load intentional; see [ADMIN_CONTROL_CENTER.md](ADMIN_CONTROL_CENTER.md) |
| Admin UX Epic (grouped nav + tab contract GC-A01–A07) | ✅ |
| GC-000 v2 — Regeln 15–17 (Parallel Systems, Duplicate Math, Owners) | ✅ |
| **GC-536** — [Queue Card UX](GC-536_QUEUE_CARD_UX.md) (536A–F ✅) | ✅ |
| **GC-557** — [Megabunker UX Feedback Polish](GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md) (557A–F) | 📋 |
| **GC-622** — [Integer Overflow Audit](GC-622_INTEGER_OVERFLOW_AUDIT.md) (INT32-Risiko geschlossen) | ✅ |
| **GC-622B** — [Resource INTEGER Migration](GC-622B_RESOURCE_INTEGER_MIGRATION.md) | 💡 |

### Tech debt (pytest, nicht blockierend)

| Item | Notizen |
|------|---------|
| `test_messages_js_spy_report_and_category_label` | `renderSpyReport` nach Inbox-Refactor umbenannt/entfernt — Test anpassen |
| `test_no_undocumented_location_reload_in_game_static` | Allowlist-Zeilen an `main.js` Drift anpassen (GC-BETA-001) — ✅ 2026-07-31 |

---

## Verwandte Dokumente

- [CAPABILITY_STATUS.md](CAPABILITY_STATUS.md) — Was es kann / was es noch verträgt (Prioritäten ohne Postgres)
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Genesis 2.0 Design Manifest (EPIC-15)
- [BETA_GATE.md](BETA_GATE.md) — Alpha-Exit, Core Architecture Freeze, Versionsstrategie
- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md) — Definition of Complete / Reifegrade
- [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md) — Strategisches Gap-Audit
- [GC-622_INTEGER_OVERFLOW_AUDIT.md](GC-622_INTEGER_OVERFLOW_AUDIT.md) — INT32/Overflow Tech-Audit ✅
- [ARCHITECTURE.md](ARCHITECTURE.md) — Systemübersicht
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle Tests
- [SECURITY.md](SECURITY.md) — Phase 6 Details
- [CONTRIBUTING.md](CONTRIBUTING.md) — Ticket-Workflow
