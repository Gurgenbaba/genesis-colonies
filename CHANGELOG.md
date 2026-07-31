# Genesis Colonies — Changelog

Vollständige Entwicklungshistorie von Projektstart bis heute.  
Clustered by milestone versions (not every commit).  
Stand: **2026-07-31** · Spieler-Meilenstein **v0.9 Alpha** · Build-Zähler [`VERSION`](VERSION) (intern / Cache-Bust, derzeit `0.5.9.x`)

> **Versionsregel:** Alpha bleibt **`v0.9.x`**. **`v1.0` / `v1.0.0-beta`** ist der Beta-Gate ([docs/BETA_GATE.md](docs/BETA_GATE.md)) — nicht für Alpha-Patches verwenden.  
> Spieler: Patchnotes live unter **News** (`/news`) und im NEWS-Banner.  
> Admins: Release-Publisher im Admin-Panel → Server → Universums-News (nicht Git-Commits).

---

## v0.9 — LiveOps & World Events *(Alpha · 2026-07-31)*

### Added
- **World Boss Events** — Encounter-Stage, Sofort-Angriff, Auto-Angriff
- **Zähmen** in Phase 3 (10 %, 10h Timekeeper, 1h Cooldown); erfolgreiches Zähmen beendet den Live-Boss und zahlt Belohnungen an Teilnehmer aus
- **Titanen** auf der Übersicht mit Titan-Link Popover (Mission-Fortschritt, sofortiges Zurück-Sync)
- **Ark-Token-Missionen** — Patrouille / Schlag / Void-Run mit Fail-Risiko
- **Titan-Slots** — Start 1, Shop bis 4
- **Piraten-Ökosystem**
- **Login-Kalender & Battle Pass**
- **Allianz-Hub**
- **Convenience-Shop** (Stripe / PayPal)
- **Story Ops / Lore** Sidequests mit Free-Shop Ark-Token Loop
- **Universe News Release-Publisher** — kuratierte Spieler-Patchnotes ohne Git-Runtime
- **Commander Classes (EPIC-27)** — 5 Klassen, linearer Skill-Trunk, Capstones, TK-Swap (`/skilltree`)
- **Commander Pick UI** — Destiny-style Command Staff cards, Living Focus, Compact Skillmap

### Changed
- Codex Quick-Help-Banner auf Seiten entfernt (Codex über Context-Button)
- Titan-Link Mission-Progress: Mini-Titan wandert Richtung Fortschritts-Spitze und zurück (Ping-Pong, reduced-motion-sicher)
- Titanen größer und mit Aura (helle + dunkle Landscapes); Hotspot ohne Auswahl-Rahmen
- World Boss Action-Bar: Angriff / Auto / Zähmen vereint
- Performance & Live-Updates gehärtet
- News: Git-Audit aus Spieler-Pfad entfernt; Whats-New nur Major Releases

### Fixed
- Diverse Sync-/PJAX-Themen
- Timer- & Queue-Stabilität
- Timekeeper-Finish: Karten-Locks / Afford / Stock nach Boost-Abschluss via include_panel Refresh
- Commander: Fuel-Efficiency-Polarität, Cargo-Multiplier in Fleet, Skilltree %-Chips, Klasse auf PlayerCard
- World Boss: ×1/×5 Hit-Grid (×5 = 5× Schaden + 25 Min CD), stabile Button-Breiten
- Tech-Tree: aktive Fleet-Research nicht mehr „vorbereitet“; Siege-Rolle; Research-Effekt-Previews
- Planet Breaker: neues Cutout-Art + Fleet-Picker Siege-Gruppe
- Titan-Link ETA sofort; WB Claim nach Kill ohne Manual-Refresh; kompakte Claim-Leiste; ×5 über Wave-Cap mit Jitter
- Tech-Tree Max-Level (Gebäude real / Forschung Soft-L50 bzw. Interstellar L6)
- Viele kleine Darstellungsfehler aus dem Alpha-Feedback
- Commander Pick-Cards: Preview-Chips nicht mehr am Kartenfuß abgeschnitten; Role-Icons als transparente WebP
- Commander Pick: Session-Fehlalarm behoben (POST/JSON statt GET → kein Login-Redirect)
- Commander Skilltree: Compact Map + Dock-Unlock statt Listen-/Path-Cards
- Titan-Link: Mission-Ende wird sofort sichtbar (kein langes Warten auf Worker)

---

## v0.8 — UX Polish & Alpha Hardening *(2026-06)*

### Added
- **Empire-Übersicht** mit Kolonie-Matrix, collapsible Sektionen (GC-620)
- **Combat Hall of Fame** mit automatischer Kampfaufzeichnung und Backfill
- **Universe Records** — Spitzenreiter für Gebäude & Forschung
- **Referral-System** mit Tier-Belohnungen (GC-703)
- **Galaktische Direktiven** — empire-weite Effekte & Nav-Badges
- **Galaktische Diplomatie** — Blöcke, Resolutions, Emergencies
- **Messages Inbox** — Bulk-Aktionen, PJAX-Lifecycle, GC-625
- **World Inspector Mission Actions** vom Command Center (GC-598)
- **Header Language Switcher** — DE/EN mit Full-Page-Reload
- **Universe News System** — Live-Banner + Archiv `/news` (GC-642)
- **Global Fleet HUD** — aktive Missionen in der Kopfleiste
- **Fleet & Logistics UI Redesign** — PJAX-Partials, Genesis HUD-Styling

### Changed
- **Sidebar-Restrukturierung** — Kommando, Infrastruktur, Militär, Wirtschaft, Verwaltung (GC-621)
- **Role-based Sidebar** — Kolonie-Rollen priorisieren Nav-Module (GC-591)
- **Building/Research Hero Cards** — Queue-Slots, Progress Variant B (GC-536, GC-550C, GC-557G)
- **Megabunker UX Polish** — Ressourcenleiste, Timer, Trader-Limits (GC-557, GC-558)
- **Overview Dashboard** — Production-first Ressourcen (GC-552)
- **Compact Number Formatting** — zentrale `fmt_int` / Mrd.-Fix
- **PlayerCard** — Avatar-Upload, Zoom-Lightbox, 40-Zeichen Commander-Name
- **Landing / Auth** — Immersive Hero, Ambient Sound, Glass-Terminal Login
- **WebP Asset Pipeline** — optimierte Bildladung (GC-549)

### Fixed
- **Wirtschaft/Trader Hub auf Kolonien** — Sidebar-Section verschwand bei Rollenfiltern (GC-641/641B)
- **Live-State Poll Storms** — Shipyard/Defense/Score-Delta (GC-546A–546E)
- **SQLite Lock Timeouts** — game-state, Queues, Galactic Directives (GC-547, 5e3b474)
- **GPU/Compositor Idle** — Landscape sichtbar in perf-idle (GC-547/548)
- **Planet Switch** — Cards, Production, Ressourcen nach Kolonie-Wechsel
- **Queue Card Timers** — kanonische Semantik, same-type sequential jobs (GC-537)
- **Messages PJAX** — Inbox-Load-Races, stale unread badge
- **Integer Overflow Audit** — Production-UI safe paths (GC-622)
- **Nav Active Highlight** — single sidebar selection
- **Locale Reality Sync** — DE/EN Copy aligned with live features (GC-620B)

### Technical
- Regression Guards: Sidebar section wrappers, always-prominent empire modules (GC-641B)
- Tests: 500+ pytest inkl. fleet logistics, galactic diplomacy, static live contracts

---

## v0.7 — Command Map & Genesis 2.0 *(2026-05 – 2026-06)*

### Added
- **Command Map MVP** — Hub-and-Spoke Graph, Pan & Zoom (GC-563/563B)
- **Spatial Command Map** — Sternenkarte, Nebel, freie Knoten (GC-564B)
- **Regions & Sectors** — Panel-Bänder, Teaser-Sites (GC-564)
- **Chokepoints & Gates** — Helios Corridor (GC-565)
- **Influence Layer** — Eigenreich-Territorium (GC-566)
- **Expansion Sites v2** — Inspector, Versprechen (GC-567/567B)
- **World Map & Role Actions** — kolonie-spezifische Quick Actions (GC-570)
- **Dynamic Colonization** — Expansion Gates, UX Polish (GC-582/582F)
- **Expedition Worlds** — gewichtete Events, Activity Feed (GC-583A–583D)
- **Empire Identity Layer** — Homeworld vs. Kolonie-Rollen, Switcher-Icons (GC-560)
- **Strategic Worlds Presentation** (GC-581)
- **Foreign Empire Presence** auf der Karte (GC-599A)
- **Command Map DEV Preview** + Foreign Node Fallback (GC-597D/E)

### Changed
- Planet Evolution als zentrales Fortschrittssystem (Gameplay-fokussiert)
- Galaxy → Command Map als Empire Screen (EPIC-15)

### Technical
- Master docs: `IMPERIUM_VISION.md`, GC-563–583 Specs
- Viewport-aware sector loading (GC-580B/C)

---

## v0.6 — Social, Ranking & LiveOps *(2026-05 – 2026-06)*

### Added
- **Vote Center** — Multi-Provider (TopG, GameToor, GTop100, Arena-Top100) + Rewards (GC-551–556)
- **Auction House** — Lootbox-Auktionen, Terminal-UI (GC-550/550B)
- **Inventory & Lootboxes** — Container-System, Daily Free Open, Boosters, Datacore (GC-540)
- **PlayerCard** — globales Profil-Modal, Edit-Flow, Security Hardening
- **Messages** — Inbox, Compose, Flotten-/Kampf-/Spionage-Reports
- **Chat** — Rooms, DM, Alliance Room, Admin Moderation
- **Support Tickets** — Spieler + Admin
- **Ranking** — Live API, Fleet/Building/Research Scores, Rank Snapshots
- **Hall of Fame / Records** — Meta-Spitzenreiter

### Changed
- Trader Hub → **Wirtschaft**-Section mit Trader Hub, Empire, Vote Center, Auktionshaus
- Inbox-Reports lokalisiert pro Spieler-Locale

### Fixed
- PlayerCard ranking lock-safe reads
- Chat panel open path after polling dedupe
- Vote provider cooldowns hard on click (GC-557A)

---

## v0.5 — Combat & Defense *(2026-05 – 2026-06)*

### Added
- **Planet Defense System** — Türme, Schilder, Defense Queue (GC-416)
- **Combat Resolver** — `simulate_battle`, Rapid Fire, EffectResolver-Boni
- **Combat Reports** — Inbox-Modal, symmetrische Koordinaten, Tech-Levels
- **Debris & Loot** — post-combat economy integration
- **Recycler Mission** — Trümmer abbauen (GC-800A/B)
- **Advanced Spy Reports** — tiered intel (GC-401)
- **Espionage Attack Path** + Dev Combat Sim

### Fixed
- Fleet countdown stuck at zero on short flights (GC-403C, multiple fleet timer fixes)
- Coordinate links in messages blocking navigation
- Defense category removed from PlayerCard score display

### Technical
- Master docs: `COMBAT_SYSTEM.md`, `DEFENSE_SYSTEM.md`
- `tests/test_combat.py` (36+ tests)

---

## v0.4 — Galaxy & Fleet *(2026-05 – 2026-06)*

### Added
- **Galaxy View** — Koordinaten, Suche, Minimap, Planet-Slots
- **Shipyard Queue** — progressive delivery, live UI (GC-403A)
- **Fleet Hub** — Send, Hold, Attack, Transport, Colonize, Recycle, Expedition
- **Expedition Event Engine** — weighted events, sci-fi report UI (GC-402A–402C)
- **Collect Mission** — Ressourcen einsammeln (GC-403)
- **Fleet Logistics** — Collect & Distribute Bulk API + `/logistics` UI (GC-900A–900E, GC-526–533)
- **Fleet Presets & Tactical Send HUD** (GC-521–525)
- **Fleet Slots** — skaliert via `navigation_tech` (GC-537)
- **Trader Hub** — Unified Exchange, Scrapyard, Fuel Exchange
- **Planet Landscapes** — slot-keyed backgrounds (WebP-optimiert)

### Fixed
- Planet scope sync across fleet, shipyard, trader hub
- Colonization flow + fleet live refresh after send
- SQLite locks under concurrent fleet/queue requests
- Logistics cargo ship gate, collect slot caps (GC-533)

### Technical
- `fleet_calc.py` canonical flight times — no frontend math (GC-000)
- Master doc: `FLEET_SYSTEM.md`, `GALAXY_SYSTEM.md`

---

## v0.3 — Planet Scope & Colonies *(2026-05)*

### Added
- **Active Planet Scope** — `active_planet_id`, `get_context_planet()`
- **Header Planet Switcher** — alle Kolonien, Koordinaten, Rollen-Icons
- **Kolonisierung** — Fleet-Mission + API
- **Planet Evolution** — DNA, Traits, Level, Policies, Events
- **Planet Research** — separat von Account-Tech
- **Trade Routes / Economy Chains**
- **Planet löschen** (Non-Homeworld)
- **Overview** — OGame-style Kolonie-Status, Planet-Manage-Modal
- **Planet Limit** im Header (GC-534)

### Fixed
- Build/Research queues planet-scoped; stuck short jobs
- Ownership safety on all planet-bound APIs
- Exchange & PE dashboard scoped to active planet

### Technical
- Master docs: `PLANET_SCOPE.md`, `PLANET_EVOLUTION.md`
- Migration hardening: `player_id`, `is_homeworld` on planets

---

## v0.2 — Economy Core *(2026-05)*

### Added
- **Auth** — Register, Login, Logout, Session
- **Ressourcen-Tick** — Ferronit, Crytite, Brennzellen, Energie
- **EffectResolver** — kanonische Produktions-/Kosten-Math
- **Buildings** — bauen, upgraden, Kategorien, Queues
- **Account Research** — Tech-Tree, Research Queue
- **Queue Engine** — zentral, finish-before-mutate, reschedule on cancel
- **Ranking & Player Scores**
- **SPA/PJAX Navigation** — `GC.navigateTo`, no full reload
- **Live Polling** — `/api/game-state`, rAF Queue UI
- **Admin Balance Tab** — Pacing Presets, validated API
- **Brennzellen-Depot** — dedizierter Fuel Storage (GC-535)

### Changed
- Buildings & Research UI Redesign (Genesis card layout)
- Medium browsergame pacing preset

### Fixed
- Live effect refresh for research/building queues
- Empire-wide research lab requirement lookup
- Idempotent build/research APIs

### Technical
- Master docs: `ECONOMY_SYSTEM.md`, `BUILDINGS_SYSTEM.md`, `RESEARCH_SYSTEM.md`, `EFFECTS.md`
- Race-condition tests (`test_race_conditions.py`)

---

## v0.1 — Foundation *(2026-05-25)*

### Added
- **Initial Alpha Snapshot** — Flask + SQLite + Jinja2
- **SQL Migrations** — numbered pipeline (`migrate.py`)
- **Installer** — `scripts/install.py`
- **Research Queue** + smooth progress bars
- **SPA Architecture** — PJAX shell, page module lifecycle
- **Persistence Layer** — multi-user planets, schema hardening
- **Admin Control Center** — Server settings, resources, wipe, bans
- **Production Deployment** — Docker, Gunicorn, Railway entrypoint
- **Health Endpoint** — `/health`
- **pytest Suite** — foundation for CI
- **Documentation** — ARCHITECTURE, SECURITY, ROADMAP, CONTRIBUTING

### Technical
- `game/db.py` abstraction, bootstrap & migration guard
- GC-000 architecture rules codified in `CORE_ARCHITECTURE.md`

---

## Version Map (Quick Reference)

| Version | Focus | Epic / Phase |
|---------|--------|--------------|
| v0.1 | Flask, DB, Migrations, PJAX shell | Phase 0 |
| v0.2 | Ressourcen, Gebäude, Forschung, Queues | Phase 1 · EPIC-04/06/07 |
| v0.3 | Multi-Kolonie, Planet Scope, Evolution | Phase 3 · EPIC-01/05 |
| v0.4 | Galaxy, Fleet, Logistics, Trader Hub | Phase 4 · EPIC-02/03 |
| v0.5 | Combat, Defense, Recycler, Spy | Phase 4b · EPIC-08 |
| v0.6 | Vote, Auction, Inventory, Social, Ranking | Phase 5 · EPIC-10 |
| v0.7 | Command Map, Influence, Expansion, Worlds | Phase 9 · EPIC-15 |
| v0.8 | Sidebar, Cards, Performance, Alpha polish | GC-536–641, GC-620+ |

---

## Sources

Built from:

- `git log --oneline --reverse` (277 commits, 2026-05-25 → 2026-06-18)
- `docs/ROADMAP.md`, `docs/PROJECT_INVENTORY.md`, `docs/EPICS.md`
- GC ticket specs in `docs/GC-*.md`

---

## Unreleased / Next

- **GC-650** — Patch Notes versioning (version tags, categories, badges on `/news`)
- **GC-700** — Combat polish gaps (no resolver rebuild)
- **Alliance Hub** — Gründung, Rechte, Diplomatie (EPIC-09)
- **PostgreSQL / Multi-Worker** — Phase 7 Platform Scale
