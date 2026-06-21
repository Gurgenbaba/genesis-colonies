# Genesis Colonies — Project Inventory

**Stand:** GC-601B (2026-06-05) — Doc-Reality-Sync; Logistics GC-900E ✅.

Audit-Methode: Module in `game/`, Routen in `app.py`, UI in `templates/` + `static/main.js`, pytest-Dateien, Master-Docs.

**Status-Legende:** ✅ Done · 🔄 Partial · 📋 Planned · ⚠️ Tech Debt · ❌ Missing

| System | Backend | UI | API | Tests | Status | Nächster Schritt |
|--------|---------|----|-----|-------|--------|------------------|
| **Overview** | `overview_page.py`, `live_state.py` | `/overview`, `GC.modules.overview` | `GET /api/game-state` | `test_game_state_live`, `test_progression_pages` | ✅ | — |
| **Buildings** | `buildings.py`, `queue_engine` | `/buildings`, PJAX | `POST /api/buildings/*` + `state` | `test_race_conditions`, `test_queue_static_contract` | ✅ | — |
| **Research** | `research.py` | `/research`, PJAX | `POST /api/research/*` + `state` | `test_race_conditions`, `test_research_requirements` | ✅ | — |
| **Trader Hub** | `exchange.py`, `scrapyard.py`, `fuel_exchange.py` | `/trader-hub` | `POST /api/exchange`, `/api/trader/scrapyard` | `test_trader_hub`, `test_exchange`, `test_scrapyard` | ✅ | — |
| **Shipyard** | `shipyard.py`, `shipyard_queue.py` | `/shipyard` (`orbital_shipyard`) | `/api/shipyard*` (`{ok,data}`) | `test_shipyard.py`, `test_shipyard_queue`, `test_fleet` | ✅ | ⚠️ Envelope → `{ok,state}` (GC-512D) |
| **Defense** | `defense.py`, `defense_api.py`, `defense_defs.py` | `/defense` | `/api/defense*`, `{ok,state,queue,defenses}` | `test_defense_phase1`, `test_defense_detail_modal` | ✅ | GC-600 done; Seiten-Poll dokumentiert |
| **Fleet** | `fleet.py`, `fleet_calc.py`, `fleet_api.py` | `/fleet` | `/api/fleet/*` | `test_fleet.py` (groß) | ✅ | — |
| **Galaxy** | `galaxy.py` | `/galaxy`, PJAX | `GET /api/galaxy/system` | `test_galaxy.py` | ✅ | — |
| **Combat** | `combat.py`, `combat_models.py` | Reports in Messages | Kein eigener Spieler-POST; Tick in `fleet.py` | `test_combat.py` (36 Tests) | ✅ | GC-700 = Lücken/Polish, kein Greenfield |
| **Recycler** | `combat.py` debris + `fleet.py` mission `recycle` | `/fleet` + Galaxy debris actions | `send_fleet` / preview | `test_recycler.py` | ✅ | GC-800C UX optional |
| **Logistics** | Collect ✅ / Distribute ✅ | `/logistics` (Collect + Distribute) | `…/collect`, `…/distribute` + `state` | `test_fleet_logistics.py` | ✅ | `auto_cargo` optional (Phase 2) |
| **Messages** | `messages.py` | `/messages`, `messages.js` | `/api/messages/*` | `test_messages.py` | ✅ | ⚠️ `href`-Fallback (GC-512C) |
| **Chat** | `chat.py` | Shell + `chat.js` | `/api/chat/*` (eigenes Poll) | `test_chat.py`, `test_chat_init` | ✅ | Ausnahme GC-000 dokumentiert |
| **Alliance** | `alliance.py` (minimal) | `/alliance` Platzhalter | — | — | 🔄 | Gründung, Rechte, Diplomatie |
| **Planet Evolution** | `planet_evolution/` | `/planet-evolution` | `/api/planets/<id>/*` + `state` | `test_planet_evolution*.py` | ✅ | ⚠️ Client `reloadCurrentPage` (GC-512A) |
| **Ranking** | `ranking.py`, `scoring.py` | `/ranking` | `GET /api/ranking` | `test_ranking.py` | ✅ | — |
| **Admin** | `admin.py`, `admin_api.py` | `/admin`, `admin.js` | `/api/admin/*` | `test_admin_*` | ✅ | ⚠️ Legacy Forms parallel |
| **Support** | `support.py` | Options/Support UI | `/api/support/*`, admin support | — | ✅ | Mehr pytest optional |
| **Options** | `options.py`, `account_email.py` | `/options`, `options.js` | `/api/options/*` | `test_options.py`, `test_account_email` | ✅ | — |

---

## GC-000 Schnellcheck (Inventory)

| Regel | Befund |
|-------|--------|
| No Full Reload | ✅ pytest Allowlist; PE/Shipyard nutzen PJAX-Reload |
| Single Source of Truth | ✅ `GET /api/game-state`; Actions mit `state` (Defense kanonisch) |
| No Parallel game-state Poll | ✅ `test_queue_static_contract` |
| Queue finish + reschedule | ✅ Build/Research GC-510; Defense/Shipyard `recalculate_*` |
| Planet Scope | ✅ `get_context_planet()` / `resolve_owned_planet_id` |
| Owner-Module | ✅ siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 |

Offene **Tech Debt** (kein Blocker): [GC-512_ARCHITECTURE_VALIDATION.md](GC-512_ARCHITECTURE_VALIDATION.md) Follow-ups GC-512A–D.

---

## Doc-Reality Gaps (GC-601)

| Doc | Problem | Korrektur |
|-----|---------|-----------|
| `ARCHITECTURE.md` Systemdiagramm | `defense*`, `combat*` nicht in `game/`-Liste | Ergänzt in GC-601 |
| `ROADMAP.md` Phase 4 | Combat/Defense ✅ — korrekt; GC-700 war als „neu bauen“ missverständlich | GC-700 = Readiness/Polish |
| `DEFENSE_SYSTEM.md` | Beschreibt teils Combat — korrekt verlinkt | Kein Widerspruch |
| `COMBAT_SYSTEM.md` | Status ✅ — entspricht `test_combat.py` + `fleet.py` attack path | — |
| Ticket GC-600 (Defense Phase 1) | Lücke war `applyActionState` + Tests | GC-600 ✅ |
| ALPHA_TESTPLAN §9 Defense Platzhalter | Veraltet | GC-601B → §9b Live-QA |
| ROADMAP Tech Debt Recycler fehlt | Veraltet (GC-800 ✅) | GC-601B entfernt / GC-800C optional |

---

## GC-700 Readiness (Combat — vorbereiten, nicht implementieren)

### Vorhanden

- **Resolver:** `game/combat.py` — `simulate_battle()`, loot (`apply_combat_loot`), debris (`spawn_combat_debris_at_planet`), reports (`publish_attack_combat_report`)
- **Modelle:** `game/combat_models.py` — Stats für Schiffe + Defense, Rapid Fire
- **Integration:** `game/fleet.py` — Attack-Arrival: simulate → losses → debris → ranking → loot → inbox
- **Defense-Anbindung:** `planet_defense` in `simulate_battle` / `split_defender_losses`
- **Effects:** `EffectResolver` Waffen/Schild/Panzer-Boni
- **Spy/Intel:** Tier-5 Defense in `spy.py`
- **Tests:** `tests/test_combat.py` (36), Fleet-Spy/Attack in `test_fleet.py`
- **Docs:** [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) aktuell (GC-500–510)

### Fehlt / GC-700 sinnvoller Scope

| Item | Priorität | Hinweis |
|------|-----------|---------|
| Recycler / Debris-Harvest-Mission | — | ✅ GC-800A/B (`recycle` mission) |
| Fleet Logistics Collect | — | ✅ GC-900B: `batch_type` + N× `mission=collect` |
| Fleet Logistics Distribute | — | ✅ GC-900D/E |
| Combat-Balancing / neue Missionen | P2 | Kein Resolver-Neubau nötig |
| PvP-Randfälle / Report-UX | P2 | Messages UI vorhanden |
| Dedizierte Combat-Admin-Tools | P3 | Admin hat Queue-Tools |

### Risiken

- Doppel-Implementierung von `simulate_battle` oder parallele Fleet-State-Queues
- Frontend-Kampf-Math (verboten GC-000)
- Attack-Tick Idempotenz bei Retries (`fleet.py` markiert `failed` — dokumentiert in COMBAT_SYSTEM)

### Empfohlener Scope für GC-700

**Nicht:** Combat-Engine von Null.

**Ja (Beispiele, je nach Product-Priorität):**

1. **Gap-Audit-Ticket:** Recycler (GC-800) vs. Combat-Polish trennen
2. **Combat v2 nur wenn:** neue Missionstypen, Resolver-Regeländerungen, oder Report-Format v3 — jeweils max. 3–5 Dateien, Tests in `test_combat.py`
3. **Vor GC-700:** GC-900B/C Collect, dann GC-900D/E Distribute — Roadmap-Blocker (GC-800 Recycler ✅)

---

## Architektur-Tickets (Referenz)

| Ticket | Status |
|--------|--------|
| GC-510 Queue Reschedule | ✅ |
| GC-512 Architecture Validation | ✅ |
| GC-513 Race Tests | ✅ |
| GC-600 Defense Phase 1 validation | ✅ |
| GC-601 Project Inventory | ✅ |
| **GC-806 Navigation Shell** (804–806D: dual sidebar, bottom dock, docs) | ✅ CLOSED |
| GC-700 Combat | 📋 Readiness oben — kein Greenfield |
| GC-800 Recycler | ✅ — [GC-800_RECYCLER.md](GC-800_RECYCLER.md); GC-800C UX optional |
| GC-900A Logistics spec | ✅ — [GC-900_LOGISTICS.md](GC-900_LOGISTICS.md) |
| GC-900B Collect backend (Option A, no migration) | ✅ |
| GC-900C Collect UI (`/logistics`) | ✅ |
| GC-900D Distribute backend | ✅ |
| GC-900E Distribute UI / polish | ✅ |
| GC-601B Documentation Consistency Sync | ✅ — [GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md](GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md) |

---

## Verwandte Dokumente

- [ROADMAP.md](ROADMAP.md)
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [GC-512_ARCHITECTURE_VALIDATION.md](GC-512_ARCHITECTURE_VALIDATION.md)
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md)
- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md)
