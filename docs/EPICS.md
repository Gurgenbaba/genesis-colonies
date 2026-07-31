# Epics — Genesis Colonies

Epics sind **Ziele**, keine Implementierungsaufgaben. Jedes Epic wird in Tickets (GC-XXX) zerlegt.

Status: v1.5.9.2 (2026-06-24)

| Epic | Titel | Status | Master-Doc |
|------|-------|--------|------------|
| EPIC-01 | Planet Scope & Multi-Kolonie | ✅ | [PLANET_SCOPE.md](PLANET_SCOPE.md) |
| EPIC-02 | Fleet System | ✅ | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| EPIC-03 | Galaxy System | ✅ | [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| EPIC-04 | Economy & Trader Hub | ✅ | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| EPIC-05 | Planet Evolution | ✅ | [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| EPIC-06 | Buildings System | ✅ | [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| EPIC-07 | Account Research | ✅ | [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) |
| EPIC-08 | Defense & Combat | ✅ | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md), [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
| EPIC-09 | Alliance Hub | ✅ | MVP + UX-Pass (Visitor `/alliance/<id>`, Spenden-Klarheit, Hub-IA) — [ALLIANCE_SYSTEM.md](ALLIANCE_SYSTEM.md) |
| EPIC-10 | Social (Chat, Messages) | ✅ | ARCHITECTURE |
| EPIC-11 | Security Hardening | 📋 | [SECURITY.md](SECURITY.md) |
| EPIC-12 | Platform Scale (Postgres) | 📋 | ARCHITECTURE · Phase 7 |
| EPIC-19 | Performance Core (Maximum Speed Stack) | 🔄 | [GC_PERF_CORE.md](GC_PERF_CORE.md) |
| EPIC-13 | Queue Card UX | ✅ | [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) |
| EPIC-14 | Megabunker UX Feedback Polish | 📋 | [GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md](GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md) |
| EPIC-15 | Imperium & Expansion (Genesis 2.0) | 📋 | [IMPERIUM_VISION.md](IMPERIUM_VISION.md) |
| EPIC-17 | Imperial Directives (High Command) | 📋 | [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) |
| EPIC-16 | Genesis Knowledge Base (Knowledge Pipeline) | 📋 | [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md) |
| EPIC-18 | Collector Exchange (Sammler-Markt) | 📋 | [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md) |
| EPIC-20 | World Boss Events | 🔄 | [WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) — GC-WB-TAME companions |
| EPIC-21 | Pirate Ecosystem (Living Threat) | ✅ | [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md) |
| EPIC-22 | LiveOps Retention (Login + Battle Pass) | ✅ | [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md) |
| EPIC-23 | Payment / Shop | ✅ | [PAYMENT_SHOP.md](PAYMENT_SHOP.md) · GC-2300…2306 |
| EPIC-24 | Admin Control Center UX | ✅ | [ADMIN_CONTROL_CENTER.md](ADMIN_CONTROL_CENTER.md) · GC-A01–A07 |
| EPIC-25 | Genesis Story Ops (Lore / Side Ops) | 🔄 | [GENESIS_STORY_OPS.md](GENESIS_STORY_OPS.md) · [GENESIS_LORE_BIBLE.md](GENESIS_LORE_BIBLE.md) · GC-2500…2518 (Jahres-Lore + Free Shop / Ark-Token) |
| EPIC-26 | Living Inactives + AI Expeditions | 🔄 | [INACTIVE_AUTOPLAY.md](INACTIVE_AUTOPLAY.md) · GC-2600…2620 |
| EPIC-27 | Commander Classes & Skill Trees | 🔄 | [COMMANDER_CLASSES.md](COMMANDER_CLASSES.md) · GC-CLASS-000…007 |

---

## Beispiel-Zerlegung

**EPIC-02 Fleet** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-301 | Fleet Planet Scope Sync |
| GC-301A | Fleet refresh nach Planetwechsel (main.js) |
| GC-301B | Preview nutzt active planet |
| GC-301C | Forms senden korrekte origin_planet_id |

**EPIC-13 Queue Card UX** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-536A | Queue Card Contract (`game/queue_card.py`) |
| GC-536B | Building Cards — Queue aus Seitenkopf |
| GC-536C | Research Cards |
| GC-536D | Shipyard Cards |
| GC-536E | Planet Evolution / Ascension Cards |

Details: [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) · [WORKFLOW.md](WORKFLOW.md)

**EPIC-14 Megabunker UX** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-557A | Ressourcenleiste — Icons, Kontrast, Mobile |
| GC-557B | Navigation — logische Gruppen |
| GC-557C | Empire Copy + Mobile Page-Scroll |
| GC-557D | Trader Hub — dynamisches Tageslimit |
| GC-557E | Building Cards — Upgrade-Button |
| GC-557F | Technische-Daten-Modal (5 Level) |

Details: [GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md](GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md)

**EPIC-15 Imperium & Expansion** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-560 | Empire Identity Layer — [Spec](GC-560_EMPIRE_IDENTITY_LAYER.md) |
| GC-575 | Planet Registry — Imperiumsübersicht rechts — [Spec](GC_PLANET_REGISTRY.md) (575A MVP → 575E) |
| GC-561 | Colony Roles Extended (PlayerCard, Surfaces, v2) |
| GC-562 | Evolution Unlock Gates ([Spec](GC-562_EVOLUTION_UNLOCK_GATES.md)) |
| GC-563 | Command Map MVP ✅ ([Spec](GC-563_COMMAND_MAP_MVP.md)) |
| GC-564 | Regions & Sectors — Datenlayer + Teaser ([Spec](GC-564_REGIONS_SECTORS.md)) ✅ |
| GC-564B | Spatial Command Map — Sternenkarte ([Spec](GC-564B_SPATIAL_COMMAND_MAP.md)) ✅ |
| GC-565 | Chokepoints — Helios Corridor & Gates ([Spec](GC-565_CHOKEPOINTS.md)) ✅ |
| GC-566 | Influence Layer — Eigenreich-Fläche ([Spec](GC-566_INFLUENCE_LAYER.md)) ✅ |
| GC-567 | Expansion Sites v2 — Versprechen & Inspector ([Spec](GC-567_EXPANSION_SITES_V2.md)) ✅ |
| GC-567B | Region Landmarks ([Spec](GC-567B_REGION_LANDMARKS.md)) ✅ |
| GC-570 | World Map + Role Actions ([Spec](GC-570_WORLD_MAP_DIRECTION.md)) ✅ |
| GC-566B | Dynamic Influence ([Spec](GC-566B_DYNAMIC_INFLUENCE.md)) 📋 |
| GC-571 | Shared World Presence ([Spec](GC-571_SHARED_WORLD_PRESENCE.md)) 📋 |
| GC-569 | superseded by GC-571 | — |
| GC-568 | Territorial Warfare |
| GC-920–929 | Expansion Protocol — [Design-Charta](EXPANSION_PROTOCOL.md) 📋 (Doku only; Implementierung referenziert Charta-Abschnitte) |

Details: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) · [ROADMAP.md](ROADMAP.md) Phase 9

**EPIC-17 Imperial Directives** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-910 | Master-Doc + Architektur ([IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md)) |
| GC-911A | Schema + definitions + generator + scaling |
| GC-911B | service + lazy generation + Tests |
| GC-912A | progress + Hooks Economy/Science |
| GC-912B | Hooks Fleet/Military/Exploration |
| GC-913 | rewards + claim API |
| GC-914A | live-state + nav badges |
| GC-914B | Page UI + i18n (8 Locales) |

Details: [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md)

**EPIC-19 Performance Core** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-PERF-CORE-001 | Messbarkeit: Budgets, Diet-Bytes, Baseline |
| GC-PERF-DB-001 | PostgreSQL-Kompatibilitätsaudit |
| GC-PERF-DB-002 | PostgreSQL + Connection Pool |
| GC-PERF-WORKER-001 | Queue-/Fleet-Worker (Ausführungsort) |
| GC-PERF-STATE-001/002 | Diet-Minimierung + Delta-State |
| GC-PERF-RES-001 | Lazy Resource Accrual |
| GC-PERF-JS-001 | `main.js` Core/Pages-Split |
| GC-PERF-CACHE-001 | Definition-/Settings-Cache (+ Redis flüchtig) |
| GC-PERF-LOAD-001 | Lasttest |
| **GC-PERF-PG-SCHEMA-001** | ✅ PostgreSQL-Schema & Migration Parity — [Spec](GC_PERF_PG_SCHEMA_001.md) |
| **GC-PERF-PG-PARITY-001** | 🔄 Backend-Parität auf leerer PG-DB — [Spec](GC_PERF_PG_PARITY_001.md) |
| GC-PERF-PG-MIGRATE-001 | SQLite→Postgres Datenimport |
| GC-PERF-JS-002 | Echter `main.js`-Split |

Details: [GC_PERF_CORE.md](GC_PERF_CORE.md) · [ROADMAP.md](ROADMAP.md) Phase 7

**EPIC-16 Genesis Knowledge Base** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-950 | Charta — Informationsarchitektur ([Spec](GC-950_KNOWLEDGE_PIPELINE.md)) |
| GC-950A1 | Landkarte des Wissens — [GC-950A1](GC-950A1_INFORMATION_ARCHITECTURE.md) (kein Inhalt) |
| GC-950A2 | Player Article Blocks — 12 P1 Master-Docs (DE) |
| GC-950B | Knowledge Generator + CI (`scripts/generate_knowledge.py`) |
| GC-950C | Codex UI — Wiki → Codex, Bands I–V |
| GC-950D | Quick Help + Context FAQ (`?`-Panel) |
| GC-950E | Commander Tips — täglicher Tip aus Pool |
| GC-950F | Discord / Export Markdown |

Supersedes: GC-630 (klassisches Tutorial). Technical Data (Ebene 3) bleibt `game/technical_data.py` — nicht in Pipeline.

Details: [GC-950_KNOWLEDGE_PIPELINE.md](GC-950_KNOWLEDGE_PIPELINE.md)

**EPIC-18 Collector Exchange** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-965A | Schema + `collector_catalog.py` + Offer-Definitionen |
| GC-965B | `collector_exchange.py` — redeem, stats, game-state |
| GC-966A | Trader Hub Tab + Xenobiologe-Panel |
| GC-966B | Schrottmeister + Wrackrekonstruktion |
| GC-966C | Energieingenieur + Hypertechniker |
| GC-967 | Inventar-Hints + Progress deep-links |
| GC-968 | Neue Booster/Utility-Items + EffectResolver |
| GC-969 | Prestige — Milestones, Titles, Profile |
| GC-969B | Loot-Reveal Toast + Codex Player Block |

Details: [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md)

**EPIC-21 Pirate Ecosystem** → nicht als Ganzes implementieren:

| Ticket | Fokus |
|--------|-------|
| GC-P00 | Master-Doc + CORE/EPICS/ROADMAP |
| GC-P01 | Schema + `game/pirates/` + AI flag |
| GC-P02 | Heat-Hooks + Galaxy Heat UI + News |
| GC-P03–P05 | Basen spawn / destroy / escalate |
| GC-P06–P08 | Spy→Intel→Attack Brain + Admin Bot-Log |
| GC-P09–P10 | Fraktionen + Bounty |
| GC-P11–P12 | `pirate_war` Emergency + Diplomacy |
| GC-P13–P15 | Hinterhalt, Infiltration, Schmuggler, Fleet-Save |
| GC-P16–P18 | Directives, LiveOps, E2E Ship-Gate |
| GC-P19–P20 | Living bots + Seed Ark colonize / planet floor |
| GC-P21–P25 | Living economy + defense fleet-save + AI colony destroy |
| GC-P26–P31 | Player-loop brain, cheat teardown, 6 factions, human colony wipe |

Details: [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md)
