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
| EPIC-09 | Alliance Hub | 🔄 | `/alliance` Platzhalter-UI; Backend minimal — [ROADMAP.md](ROADMAP.md) Phase 5 |
| EPIC-10 | Social (Chat, Messages) | ✅ | ARCHITECTURE |
| EPIC-11 | Security Hardening | 📋 | [SECURITY.md](SECURITY.md) |
| EPIC-12 | Platform Scale (Postgres) | 📋 | ARCHITECTURE |
| EPIC-13 | Queue Card UX | ✅ | [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) |
| EPIC-14 | Megabunker UX Feedback Polish | 📋 | [GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md](GC-557_MEGABUNKER_UX_FEEDBACK_POLISH.md) |
| EPIC-15 | Imperium & Expansion (Genesis 2.0) | 📋 | [IMPERIUM_VISION.md](IMPERIUM_VISION.md) |

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

Details: [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · [ROADMAP.md](ROADMAP.md) Phase 9
