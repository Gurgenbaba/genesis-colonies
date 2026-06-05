# Epics — Genesis Colonies

Epics sind **Ziele**, keine Implementierungsaufgaben. Jedes Epic wird in Tickets (GC-XXX) zerlegt.

Status: v1.5.3

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
| EPIC-13 | Queue Card UX | 📋 | [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) |

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
