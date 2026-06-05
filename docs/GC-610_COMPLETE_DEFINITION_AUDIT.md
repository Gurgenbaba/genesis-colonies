# GC-610 — Complete Definition Audit

**Stand:** 2026-06-05 · **Typ:** Doc-only (Definition of Complete)  
**Voraussetzung:** [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md), [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md)  
**Follow-up:** [GC-545](GC-545_LIVE_STATE_BROWSER_AUDIT.md) Browser Audit → GC-546 Fix → system-spezifische Close-Out-Tickets

---

## Fragestellung

| Audit | Beantwortet |
|-------|-------------|
| **GC-600** | Was haben wir? (Vorhanden / Teilweise / Fehlend) |
| **GC-610** | Wann ist ein System **100 % fertig** für Alpha? |

Ohne GC-610 bleibt „fast fertig“ subjektiv. Mit GC-610 wird Completion **messbar** — und die Roadmap lautet „82 % → 100 %“, nicht „noch ein Feature“.

---

## Definition of Complete (DoC)

Ein Kernsystem gilt als **100 % Alpha-complete**, wenn **alle** Kriterien der Kategorien A–F erfüllt sind:

| Kat. | Gewicht | Kriterium |
|------|---------|-----------|
| **A Backend** | 25 % | Logik serverseitig, Queue/Tick korrekt, idempotent, Owner-Modul kanonisch |
| **B API / State** | 15 % | `{ ok, state }` wo vorgesehen, Planet-Scope, kein Parallel-Poll |
| **C UI / UX** | 20 % | Seite spielbar, PJAX-Lifecycle, Fehler sichtbar, Mobile nicht kaputt |
| **D Tests automatisiert** | 15 % | pytest grün, Race/Idempotenz wo kritisch |
| **E QA manuell** | 15 % | ALPHA_TESTPLAN (oder System-Matrix) durchgespielt, Browser-Beweis |
| **F Balance / Polish** | 10 % | Spieldesign reviewt, bekannte Exploits dokumentiert oder gefixt |

**Nicht Teil von 100 % (Tier 3 / neues Feature):** Radar-Engine, NPCs, Marketplace, Seasons, Allianzkriege, Postgres.

**Reifegrad** = gewichteter Durchschnitt der erfüllten Kriterien pro Kategorie (siehe Detail-Checklisten).

---

## Übersicht — Reifegrad (Schätzung 2026-06-05)

| System | Reife | Fehlende Punkte | Balken | Nächster Close-Out |
|--------|------:|----------------:|--------|-------------------|
| **Buildings** | 95 % | 1 | █████████░ | GC-512D optional |
| **Research** | 90 % | 2 | █████████░ | Tech-Tree-Effekt-UX |
| **Trader Hub** | 85 % | 3 | ████████░░ | Legacy fuel_exchange cleanup |
| **Messages** | 85 % | 4 | ████████░░ | Filter, Archiv, GC-512C |
| **Fleet** | 80 % | 7 | ████████░░ | GC-545/546, §11 QA |
| **Shipyard** | 80 % | 6 | ████████░░ | Live-State, GC-512D envelope |
| **Defense** | 75 % | 8 | ████████░░ | §9b QA, Balance, Combat-Reports |
| **Logistics** | 75 % | 6 | ███████░░░ | §12 QA, auto_cargo optional |
| **Planet Evolution** | 70 % | 12 | ███████░░░ | Balance, QA-Matrix, Langzeit |
| **Galaxy** | 70 % | 8 | ███████░░░ | QA, SSR-Entscheid Live-API |
| **Combat** (Reports) | 70 % | 9 | ███████░░░ | GC-700 Polish, PvP-Randfälle |
| **Alliance** | 25 % | 15 | ██░░░░░░░░ | MVP Tier 2 — nach Tier 1 |

**Aggregat Tier 1 (Fleet + Logistics + Evolution + Defense + Galaxy):** ~**74 %** — nicht 95 %.

### Nach GC-545 Browser-QA (2026-06-05)

Quelle: [GC-545](GC-545_LIVE_STATE_BROWSER_AUDIT.md) — echte Browser-Findings, nicht Schätzung.

| System | Vor GC-545 | Nach Browser-QA | Δ | Hauptgrund |
|--------|----------:|----------------:|---|------------|
| Buildings | 95 % | **90 %** | −5 | F2 Requirements stale |
| Research | 90 % | **90 %** | — | stabil |
| Shipyard | 80 % | **70 %** | −10 | F3 Inventory, F5 Poll |
| Defense | 75 % | **65 %** | −10 | F4 wie Shipyard, F5 |
| Fleet | 80 % | **85 %** | +5 | Missionen + Reports ok |
| Galaxy | 70 % | **90 %** | +20 | voll funktional |
| Planet Evolution | 70 % | **85 %** | +15 | Technik ok, Balance offen |
| Messages | 85 % | **75 %** | −10 | F6 Badge |
| Ranking | 85 % | **70 %** | −15 | F1 Delta × n |
| Logistics | 75 % | 75 % | — | nicht in Session |

**Epic-Fokus nach GC-545:** Production Completion Layer → [GC-546D zuerst](GC-546_LIVE_STATE_FIXES.md).

---

## Detail — Definition of Complete pro System

Legende: ✅ erfüllt · 🔄 teilweise · 📋 offen (Alpha-Blocker) · ➖ bewusst Tier 3

---

### Buildings — 95 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Bau-Queue, Cancel+Reschedule (GC-510) | ✅ |
| A2 | EffectResolver-Zeit/Kosten | ✅ |
| B1 | `POST /api/buildings/*` + `{ ok, state }` | ✅ |
| C1 | 4 Tabs, Queue-Panel aus Poll | ✅ |
| C2 | Mobile Layout | ✅ |
| D1 | `test_race_conditions`, queue contract | ✅ |
| E1 | ALPHA §3 + GC-512 Queue QA | ✅ |
| F1 | Endgame-Balance (`planet_core_nexus`) | 🔄 selten erreicht |

**Fehlt bis 100 %:** Endgame-Balance-Review (F1) — kein Code-Blocker.

---

### Research — 90 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Account-Queue, empire lab max | ✅ |
| B1 | API `{ ok, state }` | ✅ |
| C1 | Tech-Liste, Queue-UI | ✅ |
| C2 | Combat-Tech-Effekte in UI erklärt | 📋 „prepared“ vs. aktiv |
| D1 | pytest research + effects | ✅ |
| E1 | ALPHA §4 + GC-512 §B | ✅ |
| F1 | Tech-Pacing Balance | 🔄 |

**Fehlt bis 100 %:** Tech-Tree-Tooltips für weapon/armor/shield/navigation (C2), Balance-Pass (F1).

---

### Trader Hub — 85 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Unified Exchange + Scrapyard | ✅ |
| B1 | Context planet, Tageslimit | ✅ |
| C1 | Zwei Panels, Poll-Sync | ✅ |
| D1 | `test_trader_hub`, exchange, scrapyard | ✅ |
| E1 | Manuelle Tausch-Routen (ALPHA implizit) | 🔄 |
| F1 | Legacy `fuel_exchange.py` deprecated | 🔄 |

**Fehlt bis 100 %:** Dedizierter ALPHA-Abschnitt Trader Hub; Legacy-Wrapper entfernen/ dokumentieren.

---

### Fleet — 80 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | 10 Missionen, Tick, Idempotenz (GC-524) | ✅ |
| A2 | Preview, Presets, Mass-Expedition | ✅ |
| B1 | `/api/fleet/*`, Planet-Scope Origin | ✅ |
| C1 | Fleet-Seite, Mission-Feedback (GC-402B) | ✅ |
| C2 | Preset UX (`colonize` in preset CHECK) | 📋 |
| C3 | Mobile Layout Fleet | 🔄 |
| C4 | Error Handling / block reasons sichtbar | 🔄 |
| D1 | `test_fleet.py` (groß) | ✅ |
| E1 | **Browser Live-State** (Countdown/Overview) | 📋 GC-545 |
| E2 | **ALPHA §11 Missions-Matrix** manuell | 📋 |
| E3 | **Report QA** (Ankunft vs. Rückkehr, alle Missionen) | 🔄 |
| E4 | **Recycler/Debris** End-to-End Browser | 📋 GC-800C optional |
| F1 | Mission-Balance / Slot-Economy | 🔄 |

**Fehlt bis 100 % (7 Punkte):** E1, E2, E4, C2 + Polish C3/C4/E3/F1.

**Ticket-Kette:** GC-545 → GC-546 → Fleet QA (§11) → GC-611 Fleet Close-Out (Preset CHECK, Mobile).

---

### Logistics — 75 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Collect + Distribute Backend (GC-900B/D) | ✅ |
| A2 | Reports `report_phase` (GC-530) | ✅ |
| B1 | Preview + `{ ok, state }` | ✅ |
| C1 | `/logistics` Compact UI (GC-533) | ✅ |
| C2 | `auto_cargo` / Preset-only ships | ➖ Phase 2 |
| D1 | `test_fleet_logistics.py` | ✅ |
| E1 | **ALPHA §12** manuell (2–3 Kolonien) | 📋 |
| E2 | Planetwechsel während laufender Legs (P1–P4) | 📋 |
| F1 | Cargo-Split / Slot-Kappung verständlich in UI | 🔄 |

**Fehlt bis 100 %:** E1, E2, F1 (auto_cargo bewusst später).

---

### Defense — 75 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Queue, Lieferung, Cancel 60 % | ✅ |
| A2 | Combat `planet_defense` in `simulate_battle` | ✅ |
| B1 | `{ ok, state, queue, defenses }` | ✅ |
| C1 | `/defense` Parität Werft | ✅ |
| C2 | Combat-Report zeigt Defense-Verluste klar | 🔄 |
| C3 | Debris-/Recycler-Sichtbarkeit aus Defense-Perspektive | 🔄 |
| D1 | `test_defense_phase1`, detail modal | ✅ |
| E1 | **ALPHA §9b** manuell | 📋 |
| F1 | **Balancing** Einheiten-Kosten/Power | 📋 |
| F2 | Ranking Defense-Score spiegelt Stock | ✅ |

**Fehlt bis 100 %:** E1, F1, C2/C3 Polish.

---

### Planet Evolution — 70 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | DNA, Planet-Tech, Events, Ascension, Policies | ✅ |
| A2 | Tick in `update_planet_resources` | ✅ |
| B1 | `/api/planets/<id>/*` Owner-Check | ✅ |
| C1 | Dashboard `/planet-evolution` | ✅ |
| C2 | Spieler versteht DNA/Specialization ohne Wiki | 📋 |
| D1 | `test_planet_evolution*.py` | ✅ |
| E1 | **QA-Matrix** (DNA-Pfade, Events, Ascension Langzeit) | 📋 fehlt in ALPHA |
| E2 | Multi-Kolonie: Evolution pro Planet getrennt getestet | 📋 |
| F1 | **Balance** Event-Häufigkeiten, XP-Kurve | 📋 |
| F2 | **Langzeitprogression** (Woche+) reviewt | 📋 |
| F3 | Tutorialisierung / Teaser Overview | 📋 |

**Fehlt bis 100 %:** 12 Punkte — größte Lücke in Tier 1 neben QA-Infrastruktur.

**Ticket-Kette:** GC-612 Evolution QA-Matrix (ALPHA §13) → GC-613 Balance-Pass.

---

### Galaxy — 70 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Koordinaten, 15 Slots + Pos. 16 | ✅ |
| B1 | `/api/galaxy/system` JSON | ✅ |
| C1 | SSR-Systemansicht, Fleet-Shortcuts | ✅ |
| C2 | Live-Slot-Refresh (Client nutzt API) | 📋 Entscheidung |
| D1 | `test_galaxy.py` | ✅ |
| E1 | Prefill + colonize/debris/recycle Shortcuts (§11.2) | 🔄 in Fleet QA |
| E2 | Dedizierte Galaxy-only QA-Matrix | 📋 |
| F1 | Radar / Deep Scan | ➖ Tier 3 Greenfield |
| F2 | NPCs, Hotspots, Alien-Zonen | ➖ Tier 3 |

**Fehlt bis 100 % (Alpha-Scope):** C2-Entscheid, E2, Fleet-QA-Abdeckung §11.2.

---

### Messages — 85 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | Fleet/Combat/Logistics/Spy/Expedition Reports | ✅ |
| A2 | GC-543/544 Inbox-Verbesserungen | ✅ |
| C1 | Kategorien, Event-Cards (GC-402C) | ✅ |
| C2 | Filter (Kategorie, gelesen) | 📋 |
| C3 | Archiv / Bulk-Aktionen | 📋 |
| D1 | `test_messages.py` | 🔄 Spy-Renderer-Test stale |
| E1 | Badge sofort nach Lesen (GC-545 Flow) | 📋 |
| F1 | Report-UX Combat/Logistics einheitlich | 🔄 |

**Fehlt bis 100 %:** C2, C3, E1, pytest GC-512C.

---

### Alliance — 25 %

| # | Kriterium | Status |
|---|-----------|--------|
| A1 | `alliance.py` minimal, Hold-Gate, Chat-Room | 🔄 |
| B1 | Gründung / Beitritt API | ❌ |
| C1 | `/alliance` Hub UI | ❌ Platzhalter |
| C2 | Mitgliederliste, Profil | ❌ |
| D1 | pytest | ❌ |
| E1 | Manuelle QA | ❌ |

**100 % = MVP (Tier 2):** Gründen, Beitreten, Liste, Profil, Chat — **nach** Tier 1 Close-Out.

---

## Roadmap nach GC-610

Statt Feature-Sprung:

```
Fleet        80 → 100 %   (GC-545, GC-546, §11, Preset/Mobile)
Logistics    75 → 100 %   (§12, Planetwechsel-Legs)
Defense      75 → 100 %   (§9b, Balance)
Evolution    70 → 100 %   (§13 QA-Matrix, Balance)
Galaxy       70 → 90 %    (QA; Radar bewusst Tier 3)
Buildings    95 → 100 %   (optional Endgame-Balance)
Research     90 → 100 %   (Tech-Tree-UX)
Messages     85 → 95 %    (Filter/Archiv)
─────────────────────────
Alliance     25 → 80 %    (MVP — Tier 2)
Security     —  → 100 %   (Phase 6 — vor Public Beta)
Tutorial     0  → 80 %    (Tier 3 Retention)
```

---

## Empfohlene Ticket-Reihenfolge (aktualisiert)

| # | Ticket | Ziel-Reife |
|---|--------|------------|
| 1 | **GC-610** | DoC definiert (dieses Dokument) ✅ |
| 2 | **GC-545** | Live-State Browser Audit — blockiert E-Kriterien Fleet/Shipyard/Research |
| 3 | **GC-546** | Gezielter Live-State-Fix |
| 4 | **GC-611** | Fleet Close-Out (§11 QA + Preset CHECK + Mobile) → Fleet 100 % |
| 5 | **GC-612** | Logistics Close-Out (§12) → Logistics 100 % |
| 6 | **GC-613** | Evolution QA-Matrix + Balance-Pass → Evolution 90 %+ |
| 7 | **GC-614** | Defense Close-Out (§9b + Balance) → Defense 100 % |
| 8 | **GC-615** | Galaxy QA-Matrix → Galaxy 90 %+ |
| 9 | **GC-620** | Alliance MVP (Tier 2) |
| 10 | **GC-621+** | Security Phase 6 (KDF, Rate-Limit) — vor Public Beta |

*(GC-611–615 Nummern reserviert — Tickets bei Start anlegen.)*

**Security:** früher als GC-610/611 in GC-600 skizziert — **umbenannt auf GC-621+** wegen GC-610 DoC-Audit.

---

## Akzeptanzkriterien GC-610

- [x] DoC-Framework (Kategorien A–F) dokumentiert
- [x] Reifegrad-Tabelle für alle Kernsysteme
- [x] Pro System: Checkliste „fehlt bis 100 %“
- [x] Tier-3-Features explizit aus 100 %-Definition ausgeschlossen
- [x] Ticket-Reihenfolge GC-610 → GC-545 → Close-Outs
- [x] GC-600 / ROADMAP verlinkt und aligned

---

## Pflege

Nach jedem Close-Out-Ticket: Reifegrad-Spalte und Checklisten in diesem Doc aktualisieren. **Eine Wahrheit** mit [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) (Code) und [GC-600](GC-600_PROJECT_GAP_ANALYSIS.md) (Strategie).

---

## Verwandte Dokumente

- [GC-600_PROJECT_GAP_ANALYSIS.md](GC-600_PROJECT_GAP_ANALYSIS.md)
- [ROADMAP.md](ROADMAP.md)
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md)
- [GC-545_LIVE_STATE_BROWSER_AUDIT.md](GC-545_LIVE_STATE_BROWSER_AUDIT.md)
