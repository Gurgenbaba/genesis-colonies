# GC-600 — Project Gap Analysis

**Stand:** v1.5.4 · **Quellen:** ROADMAP, ARCHITECTURE, BUILDINGS, RESEARCH, FLEET, GALAXY, ECONOMY, PLANET_EVOLUTION, PLANET_SCOPE, ALPHA_TESTPLAN, PROJECT_INVENTORY (2026-06-05)

**Zweck:** Strategische Lückenmatrix — nicht Implementierung, sondern Entscheidungsgrundlage für die nächsten ~6 Monate. Ergänzt [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) (Code-Reality) um Product- und Gameplay-Perspektive.

**Hinweis Ticket-Nummer:** Früheres Ticket „GC-600 Defense Phase 1“ ist abgeschlossen. Dieses Dokument nutzt **GC-600** als strategisches Gap-Audit (vom Product-Owner gewünscht).

---

## Legende

| Spalte | Bedeutung |
|--------|-----------|
| **Vorhanden** | Stabil, getestet, spielbar — kein Greenfield nötig |
| **Teilweise** | Backend/UI/Tests/Balance/UX — mindestens eine Schicht unvollständig |
| **Fehlend** | Nicht implementiert oder nur Idee/Backlog |
| **Priorität** | Empfehlung nächste 6 Monate: **P0** Launch-Blocker · **P1** Hoher Spielwert · **P2** Vertiefung · **P3** Nice-to-have · **—** Bewusst zurückgestellt |

**Kategorie-Bewertung:** ⭐ (1) … ⭐⭐⭐⭐⭐ (5) — siehe Fußnote unten.

---

## System-Matrix

| System | Vorhanden | Teilweise | Fehlend | Priorität |
|--------|-----------|-----------|---------|-----------|
| **Foundation** | Flask/SQLite, Migrationen 006–040+, Bootstrap-Guard, Docker/Gunicorn, 513+ pytest, Health, GC-000 Enforcement, Queue-Engine zentral, PJAX-Shell, Idempotenz | Postgres-Backend (`NotImplementedError`), Multi-Worker, CI-Pipeline | Redis, WebSocket-Push | P2 (Scale erst vor Public Launch+) |
| **Auth & Account** | Register/Login/Logout, E-Mail-Verifikation, Passwort-Reset, Ban | — | bcrypt/argon2 KDF (SHA-256), Login/Register Rate-Limit, Session-Cookie-Hardening, CSRF HTML-Forms | **P0** (Phase 6 — Public-Beta-Blocker) |
| **Planet Scope** | `active_planet_id` DB-persistiert, Header-Switcher, Scope-Matrix dokumentiert, Queue-Finish empire-wide, Planet-Limit HUD (GC-532), Kolonie löschen | — | — | — |
| **Economy Core** | 3 Ressourcen + Energie, EffectResolver-Tick, Storage-Caps, Brennzellen integriert, Trader Hub Unified Exchange, Scrapyard, Tageslimits, Overflow-Regeln | Fuel-Exchange Legacy-Wrapper deprecated | Spieler-Marketplace, dynamische Marktpreise | P3 |
| **Buildings** | 16 Gebäude-Keys, 4 Tabs, Bau-Queue (Limit, Cancel+Reschedule GC-510), Requirements, EffectResolver-Zeit, API `{ok,state}` | Endgame-Gebäude (`planet_core_nexus` etc.) — spielerisch selten erreicht | — | P3 (Balance, nicht Architektur) |
| **Account Research** | 11 Techs, Queue (2–3 Slots), Tech-Tree, EffectResolver (Economy/Time aktiv) | Combat-Techs (`weapon/armor/shield`) als „prepared“, nicht voll in UI kommuniziert | Dedizierte Tech-Consumer außerhalb Combat/Fleet | P2 |
| **Shipyard** | `orbital_shipyard`, Queue, fuel_cells-Kosten, `planet_ships`, API | Response-Envelope noch `{ok,data}` statt kanonisch `{ok,state}` (GC-512D) | — | P3 |
| **Fleet Core** | 10 Missionen, Tick-Idempotenz, Preview, Presets, Mass-Expedition, Galaxy-Prefill, Slot-System | `fleet_presets` CHECK ohne `colonize`, `eclipse_runner` Phase-2-only | Auto-Cargo / Preset-only Logistics-Ships | P3 |
| **Fleet Logistics** | Collect + Distribute Backend (GC-900B/D), `/logistics` UI inkl. Distribute (GC-900E), Preview, Reports mit `report_phase`, pytest | `auto_cargo` Modus optional | — | P3 |
| **Galaxy** | Koordinaten G:S:P, 15 Slots + Pos. 16 Expedition, SSR-Systemansicht, Fleet-Shortcuts, Unique-Index | Live-Slot-Refresh via `/api/galaxy/system` (API existiert, Client nutzt nicht) | — | P3 |
| **Radar / Scan** | `radar_array` Gebäude, EffectResolver `scan_range` Modifier | — | Scan-Engine, Galaxy-Intel-Layer | P2 |
| **Planet Evolution** | DNA, Traits, Level/XP, Planet-Tech-Queue, Specialization, Policies, Events, Ascension, Trade Routes, Tick-Integration, Dashboard-API | UI-Dichte vs. Tiefe — viele Subsysteme, wenig Alpha-QA in Testplan | In-Page Planet-Switcher (bewusst verboten — Header only) | P2 (Depth + Balance) |
| **Kolonisierung** | Fleet `colonize`, API `POST /api/planets/colonize`, max 9 Kolonien, Koordinaten-Zuweisung | — | — | — |
| **Defense** | Queue, `planet_defense`, Ranking-Score, Spy Intel Tier 5, Combat-Integration, `{ok,state}` | — | — | P3 (Polish only) |
| **Combat** | `simulate_battle`, 6 Runden, Loot, Debris, Reports v2, Defense-Anbindung, 36+ pytest | PvP-Randfälle, Report-UX, Balancing | Dedizierte Combat-Admin-Tools, Combat v2 | **—** (GC-700 Polish only, kein Neubau) |
| **Recycler / Debris** | `recycle` Mission, `harvest_debris_at_field`, Galaxy debris actions, GC-800A/B | Recycler UX-Polish (GC-800C) | — | P3 |
| **Espionage** | Tiered probe intel (GC-401), Inbox structured reports | — | Counter-Intel, Fog-of-War | P2 |
| **Expeditions** | Weighted Event Engine (GC-402), Preview hints (402B), Event-Card Inbox (402C) | Event-Balance / Content-Erweiterung | Neue Event-Typen | P2 |
| **Ranking & Scores** | Live API, Player Scores, Combat/Defense/Military-Anteil | — | Seasonal Leaderboards | P3 |
| **Messages / Inbox** | Fleet/Combat/Logistics/Spy/Expedition Reports, Kategorien, Metadata | `href`-Fallback (GC-512C), veralteter pytest-Spy-Renderer | — | P3 |
| **Chat** | Rooms, DM, Alliance-Room, Rate-Limit in-process, Admin mute/ban | Rate-Limit nicht Redis — bricht bei Multi-Worker | — | P2 (mit Scale) |
| **Alliance** | Backend minimal (`alliance.py`), Hold-Mission Ally-Gate, Chat-Room | `/alliance` Platzhalter-UI (ALPHA_TESTPLAN §9) | Gründung, Rechte, Diplomatie, Hub-UI | **P1** |
| **PlayerCard** | Profil, Stats API | — | — | — |
| **Admin** | Control Center JSON API, Audit Log, Queue-Tools, Balance Editor, MOTD | Legacy HTML-Forms parallel, kein PJAX/State | Admin Combat-Sandbox | P2 |
| **Support** | Tickets Spieler + Admin | Wenig pytest | — | P3 |
| **Options / i18n** | Options-Seite, `game/i18n.py`, `en.json` | UI-Switch DE/EN unvollständig | Vollständige EN-Abdeckung aller Templates | P2 |
| **Tutorial / Onboarding** | — | — | Guided Tutorial, Erste-Stunden-Flow | **P1** |
| **Season / Live Ops** | MOTD, Universe Settings | Balancing-Tooling teilweise | Season Reset, Universe-Wipe-Workflow, Automated Backups | P2 |
| **Security (Phase 6)** | SECURITY.md Threat Model | — | KDF, Rate-Limits, CSRF, Headers — alles 📋 | **P0** |
| **Platform Scale** | `game/db.py` Postgres-Hooks, portable SQL | SQLite Single-Writer | Postgres-Implementierung, horizontale Skalierung | P1 (vor Growth) |

---

## Kategorie-Bewertung

| Kategorie | Bewertung | Kurzbegründung |
|-----------|-----------|----------------|
| **Early Game** | ⭐⭐⭐⭐ (4/5) | Gebäude, Forschung, Queues, Ressourcen-Tick, Trader Hub — solide Kernschleife. Schwach: kein Tutorial, Homeworld-only-Einstieg ohne Guidance. |
| **Mid Game** | ⭐⭐⭐⭐ (4/5) | Multi-Kolonie, Planet Scope, Logistics Collect/Distribute, Shipyard, Galaxy-Navigation, Planet Evolution Layer — breit, aber Evolution-Tiefe vs. UI-Komplexität unausgereift getestet. |
| **End Game** | ⭐⭐⭐ (3/5) | Ascension, Specialization, End-Gebäude, Empire-Research — Code da, Gameplay-Pacing und Balance unklar; kein Season/Meta-Loop. |
| **PvP** | ⭐⭐⭐ (3/5) | Attack + Defense + Loot + Debris + Ranking funktional. Alliance/Diplomatie fehlt; Combat-Polish (GC-700) offen; kein strukturiertes Kriegs-Meta. |
| **PvE** | ⭐⭐⭐⭐ (4/5) | Expedition-Events, Recycler, Kolonisierung, Planet-Events — starke Vielfalt. Radar/Scan und tiefere PvE-Ketten fehlen. |
| **Social** | ⭐⭐⭐ (3/5) | Chat + Messages + PlayerCard ✅. Alliance-Hub ❌ — sozialer Klebstoff fehlt; kein Marketplace. |
| **Economy** | ⭐⭐⭐⭐ (4/5) | EffectResolver-autoritativ, Exchange, Scrapyard, Logistics, Trade Routes (Evolution) — konsistent. Kein Spieler-Handel, begrenzte Spezial-Ressourcen-Sichtbarkeit. |
| **Retention** | ⭐⭐ (2/5) | Queues + Multi-Kolonie geben Anlass zum Zurückkommen. Kein Tutorial, kein Season, i18n halb, Security nicht launch-ready — Retention-Risiko nach Tag 3–7. |

**Skala:** ⭐ = kaum spielbar / fehlt · ⭐⭐⭐ = solide Basis · ⭐⭐⭐⭐⭐ = Alpha-tauglich ohne bekannte Blocker in der Kategorie.

---

## Was schon richtig gut ist

Diese Bereiche sind **kein Greenfield** — erweitern, nicht neu bauen:

1. **Architektur & Disziplin (GC-000)** — Single Queue-Engine, Planet Scope, Server Authority, PJAX, `{ok,state}` + `applyActionState`, 500+ Tests. Selten so konsistent in Alpha-Projekten.
2. **Economy Core** — Ressourcen-Tick, Energie, EffectResolver, Trader Hub — durchgängig dokumentiert und getestet.
3. **Multi-Kolonie-Operations** — Planet Switcher, Background-Queue-Finish, Logistics Bulk Collect/Distribute mit idempotenten Reports.
4. **Fleet-Missions-Stack** — Transport bis Colonize, Expedition-Event-Engine, Spy-Tiers, Recycler — breite PvE/PvP-Toolbox.
5. **Planet Evolution** — Ambitioniertes Per-Planet-Subsystem (DNA, Policies, Events) bereits an Tick und APIs angebunden.
6. **Combat/Defense** — Resolver aktiv, nicht „coming soon“; `/defense` live (ALPHA_TESTPLAN §9b, GC-601B).
7. **Admin & Ops** — Control Center, Audit, Balance Editor — über Alpha-Niveau.

---

## Was nur halb fertig ist

Priorisierte „Halbfertig“-Liste (größter ROI bei Fertigstellung):

| Bereich | Ist-Zustand | Was „fertig“ bedeutet |
|---------|-------------|------------------------|
| **Alliance** | Backend-Gates (Hold, Chat-Room), UI Platzhalter | Gründung, Rollen, Diplomatie, `/alliance` Hub — unlockt PvP-Social |
| **Security Phase 6** | Dokumentiert, nicht implementiert | KDF + Rate-Limits — **Launch-Blocker** |
| **Tutorial / Onboarding** | Backlog | Erste 30 Minuten geführt — Retention-Hebel #1 |
| **Planet Evolution UX** | Tiefe Backend-Features, dünn im Alpha-Testplan | Gezielte QA + Balance-Pass Mid/Endgame |
| **Research „prepared“ Techs** | Combat/Fleet-Modifier existieren, Kommunikation schwach | Spieler-sichtbare Tooltips / Tech-Tree-Effekte |
| **Logistics `auto_cargo`** | Collect/Distribute live (GC-900E ✅) | Preset-only / auto_cargo optional |
| **i18n** | Infrastruktur da | EN-Vollständigkeit für Public Beta |
| **Galaxy Live API** | Endpoint existiert | Entscheiden: nutzen (Live-Slots) oder bewusst SSR-only dokumentieren |
| **Radar/Scan** | Modifier only | Scan-Engine oder Gebäude aus UI entfernen bis Phase 2 |
| **Combat GC-700** | Spielbar | Randfälle, Report-UX, Balance — **kein** Resolver-Neubau |
| **Admin Legacy Forms** | Doppelt | Konsolidierung auf JSON Control Center |

---

## Was komplett fehlt

| Feature | Roadmap-Phase | Empfohlene Priorität |
|---------|---------------|----------------------|
| Passwort-KDF (bcrypt/argon2) | Phase 6 | **P0** |
| Login/Register Rate-Limiting | Phase 6 | **P0** |
| CSRF / Session Hardening | Phase 6 | **P0–P1** |
| Alliance Gründung / Rechte / Diplomatie | Phase 5 | **P1** |
| Tutorial / Onboarding | Phase 8 | **P1** |
| Spieler-Marketplace | Phase 5 💡 | P2 |
| Scan-Engine (Radar) | — | P2 |
| PostgreSQL Backend | Phase 7 | P1 (vor Skalierung) |
| Season / Universe-Reset | Phase 8 | P2 |
| CI Pipeline | Phase 8 | P2 |
| Redis (Sessions, Chat rate limit) | Phase 7 💡 | P2 (mit Multi-Worker) |
| WebSocket Push | Phase 7 💡 | P3 |
| Counter-Intel / Fog-of-War | — | P3 |

---

## Strategie: Completion-First (Alpha)

**Leitplanke:** Vor neuen Features vorhandene Kernsysteme auf **100 % fertig** ziehen — QA, UX, Reports, Balance, Live-State — nicht Greenfield.

> „Genesis Colonies hat keine halbfertigen Kernsysteme mehr.“

Security und Tutorial bleiben wichtig, aber **nach** dem Vollenden der bereits implementierten Spielschichten (Ausnahme: Security vor Public Beta).

---

### Tier 1 — Vorhandene Systeme vollenden

| # | System | Stand | Feinschliff (nicht neu bauen) | Nähe „fertig“ |
|---|--------|-------|-------------------------------|---------------|
| 1 | **Fleet & Logistics** | Missions, Collect/Distribute, Expedition, Spy, Deploy, Hold, Colonize, Recycler ✅ | Browser-Live-State ([GC-545](GC-545_LIVE_STATE_BROWSER_AUDIT.md)), Fleet QA (ALPHA §11), Logistics QA (§12), Reports, Presets, GC-800C UX | **Höchste** |
| 2 | **Planet Evolution** | DNA, Events, Ascension, Policies — Backend stark | Balance, DNA-Pfade, Events/Ascension Langzeit-QA, Testplan-Erweiterung | Hoch (USP-Potenzial) |
| 3 | **Defense** | Live (GC-600), Combat-Anbindung ✅ | Balancing, UI-Polish, Report-Integration, Debris-Sichtbarkeit | Mittel |
| 4 | **Galaxy** | SSR-Systemansicht, Fleet-Shortcuts ✅ | Radar/Deep Scan = **neu**; Hotspots/NPCs/Events = Tier 3 | Basis ✅, Erweiterung später |

### Tier 2 — Halbfertige Systeme (MVP schließen)

| System | MVP-Scope | Bewusst nicht |
|--------|-----------|---------------|
| **Alliance** | Gründen, Beitreten, Mitgliederliste, Profil, Allianzchat | Allianzkriege, Diplomatie-Deep |
| **Messages** | Reports (GC-543/544 ✅), Filter, Kategorien, Archiv | Neues Inbox-Framework |

### Tier 3 — Erst danach neue Features

Tutorial · Marketplace · Radar-Engine · Seasons · Postgres · i18n voll · Season/Meta

---

### Nächste Tickets (empfohlene Reihenfolge)

| # | Ticket | Typ | Ziel |
|---|--------|-----|------|
| 1 | **GC-610** | DoC | [Complete Definition Audit](GC-610_COMPLETE_DEFINITION_AUDIT.md) — Reifegrade ✅ |
| 2 | **GC-545** | Audit | Live-State Browser — blockiert E-Kriterien |
| 3 | **GC-546** | Fix | 1–2 Dateien aus GC-545 |
| 4 | **GC-611** | Close-Out | Fleet 80 → 100 % (§11 QA, Presets, Mobile) |
| 5 | **GC-612** | Close-Out | Logistics 75 → 100 % (§12) |
| 6 | **GC-613** | Close-Out | Evolution 70 → 90 %+ (QA-Matrix, Balance) |
| 7 | **GC-614** | Close-Out | Defense 75 → 100 % (§9b, Balance) |
| 8 | **GC-615** | Close-Out | Galaxy 70 → 90 %+ |
| 9 | **GC-620** | Feature | Alliance MVP (Tier 2) |
| 10 | **GC-621+** | Infra | Security Phase 6 — vor Public Beta |
| 11 | Tutorial | Feature | Nach Tier 1 Close-Out |

**Nicht in Top 11:** Combat-Neubau, Marketplace, Radar-Greenfield, Seasons, Postgres.

### Ticket-Ableitung (bei Bedarf)

| Gap | Ticket-Skizze | Scope |
|-----|---------------|-------|
| Definition of Complete | **GC-610** ✅ | [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md) |
| Live-State hängt | GC-545 → GC-546 | Browser Audit + 1–2 Dateien Fix |
| Fleet 80 → 100 % | GC-611 | §11, Preset CHECK, Mobile |
| Logistics 75 → 100 % | GC-612 | §12 |
| Evolution 70 → 90 %+ | GC-613 | ALPHA §13 + Balance |
| Defense 75 → 100 % | GC-614 | §9b + Balance |
| Galaxy 70 → 90 %+ | GC-615 | QA-Matrix |
| Alliance MVP | GC-620 → GC-621–625 | Kein `alliance_v2` |
| Security | GC-621+ | Phase 6 — [SECURITY.md](SECURITY.md) |
| Combat Polish | GC-700 / GC-701–705 | Randfälle, Reports — kein Resolver-Neubau |
| Tutorial | GC-630 | Overview-geführt |

---

## Doc-Reality Sync (GC-601B ✅)

| Quelle | Stand nach GC-601B |
|--------|-------------------|
| ALPHA_TESTPLAN §9 | Nur `/alliance` Platzhalter; Defense → §9b Live-QA |
| ROADMAP Tech Debt | Recycler Mission ✅ (GC-800); Tech Debt nur GC-800C UX optional |
| ROADMAP Phase 4 | Defense ✅, Recycler ✅ — unverändert korrekt |
| ARCHITECTURE / EPICS | Defense ✅; Alliance 🔄 dokumentiert |

**Offen (bewusst nicht GC-601B):** RESEARCH.md „prepared“ vs. Combat-Consumer — separates Doc-Ticket wenn Tech-Tree-UX angegangen wird.

---

## Zusammenfassung (30-Minuten-Entscheidung)

| Frage | Antwort |
|-------|---------|
| Was ist production-grade? | Foundation, Economy, Buildings, Research, Fleet, Logistics, Galaxy, Planet Scope, Defense, Combat-Kern, Messages, Chat, Admin |
| Was blockiert Alpha-Qualität? | **Messbare Lücken bis DoC 100 %** — [GC-610](GC-610_COMPLETE_DEFINITION_AUDIT.md); Tier 1 ~74 % |
| Was blockiert Public Beta? | **Security Phase 6** (P0) — nach Tier 1/2 |
| Was blockiert Sozial/PvP-Gefühl? | **Alliance MVP** (Tier 2) |
| Was blockiert Retention Tag 7? | **Tutorial** (Tier 3) + Evolution-Balance |
| Was bewusst nicht als Nächstes? | Combat-Neubau, Marketplace, Radar-Greenfield, neue Timer-Systeme |
| Größter strategischer Hebel? | **Vollenden vor Erweitern** — Fleet zuerst, dann Evolution/Defense |

---

## Verwandte Dokumente

- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md) — Definition of Complete / Reifegrade
- [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) — Code-Modul-Status (GC-601)
- [ROADMAP.md](ROADMAP.md) — Phasen & Meilensteine
- [ALPHA_TESTPLAN.md](ALPHA_TESTPLAN.md) — Manuelle QA
- [GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md](GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md) — Doc-Reality-Sync
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000 Regeln
