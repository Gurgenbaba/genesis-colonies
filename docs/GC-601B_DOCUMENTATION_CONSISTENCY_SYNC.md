# GC-601B — Documentation Consistency Sync

**Stand:** 2026-06-05 · **Typ:** Doc-only (kein Feature-Code)

Abgrenzung zu **GC-601** ([PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)): GC-601 erfasste Code-Reality pro Modul; GC-601B bringt Master-Docs auf denselben Stand wie Code und [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md).

---

## Ziel

Roadmap, Alpha-Testplan, Architektur und Epics erzählen dieselbe Wahrheit — insbesondere für zuletzt fertiggestellte Systeme (Defense, Recycler/Debris Recovery).

---

## Scope

| Datei | Änderung |
|-------|----------|
| [ROADMAP.md](ROADMAP.md) | Tech Debt: Recycler nicht mehr als „fehlend“; GC-601B eingetragen |
| [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) | Defense aus Platzhalter §9 entfernt → §9b Live-QA |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Verweise auf GC-600 + GC-601B |
| [EPICS.md](EPICS.md) | EPIC-09 Alliance-Status präzisiert |
| [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md) | Doc-Reality-Abschnitt auf Sync-Stand |
| [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) | Logistics/GC-900E an ROADMAP angeglichen |

**Nicht im Scope:** Feature-Implementierung (Security, Alliance, Tutorial, Combat, Marketplace).

---

## Akzeptanzkriterien

- [x] Defense nicht mehr als Placeholder geführt
- [x] Recycler/Debris Recovery nicht mehr als offen geführt (ROADMAP Tech Debt)
- [x] GC-600 Audit stimmt mit ROADMAP überein
- [x] Keine offenen Tickets als erledigt markieren (GC-700, Alliance, Security bleiben 📋/🔄)
- [x] Keine erledigten Features als offen markieren (Defense ✅, GC-800 Recycler ✅, GC-900E ✅)

---

## Korrekturen im Detail

### Defense

| Vorher | Nachher |
|--------|---------|
| ALPHA_TESTPLAN §9: `/defense` Platzhalter | §9b: Live-QA (Queue, Build, Cancel, Planet-Scope) |
| GC-600: „ALPHA_TESTPLAN veraltet“ | GC-601B ✅; Verweis §9b |

ROADMAP Phase 4 und ARCHITECTURE hatten Defense bereits ✅ — unverändert korrekt.

### Recycler / Debris Recovery

| Vorher | Nachher |
|--------|---------|
| ROADMAP Tech Debt: „Recycler mission (debris harvest) → Phase 4b“ | Entfernt; optional nur GC-800C UX polish |
| GC-600: ROADMAP Recycler „veraltet“ | GC-601B ✅ |

GC-800A/B ✅ seit [GC-800_RECYCLER.md](GC-800_RECYCLER.md). GC-800C (UX polish) bleibt optional — **nicht** als fehlendes System.

### Bewusst unverändert (korrekt offen)

| Item | Status in Docs |
|------|----------------|
| GC-700 Combat Polish | 📋 — kein Neubau |
| Alliance Hub | 🔄 / Platzhalter |
| Security Phase 6 | 📋 P0 |
| Tutorial / Onboarding | 💡 / fehlend in GC-600 |
| Marketplace | 💡 Backlog |

---

## Nächste Schritte (Product, nicht dieses Ticket)

Priorität laut [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md):

1. Security Phase 6 (P0)
2. Alliance MVP (P1)
3. Tutorial / Onboarding (P1)

---

## Verwandte Dokumente

- [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md)
- [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)
- [GC-800_RECYCLER.md](GC-800_RECYCLER.md)
