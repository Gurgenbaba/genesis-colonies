# Genesis Colonies — Project Inventory

**Stand:** v1.5.9.2 (2026-07-02) — Alliance MVP complete (GC-AL-MVP-09); siehe [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md) für Economy-Anker.

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
| **Combat** | `combat.py`, `combat_models.py` | Reports in Messages | Kein eigener Spieler-POST; Tick in `fleet.py` | `test_combat.py` | ✅ | GC-700 = Lücken/Polish, kein Greenfield |
| **Recycler** | `combat.py` debris + `fleet.py` mission `recycle` | `/fleet` + Galaxy debris actions | `send_fleet` / preview | `test_recycler.py` | ✅ | GC-800C UX optional |
| **Logistics** | Collect ✅ / Distribute ✅ | `/logistics` (Collect + Distribute) | `…/collect`, `…/distribute` + `state` | `test_fleet_logistics.py` | ✅ | `auto_cargo` optional (Phase 2) |
| **Messages** | `messages.py` | `/messages`, `messages.js` | `/api/messages/*` | `test_messages.py` | ✅ | ⚠️ `href`-Fallback (GC-512C) |
| **Chat** | `chat.py` | Shell + `chat.js` | `/api/chat/*` (eigenes Poll) | `test_chat.py`, `test_chat_init` | ✅ | Ausnahme GC-000 dokumentiert |
| **Alliance** | `alliance.py`, `alliance_catalog.py` | `/alliance`, `GC.modules.alliance` | `/api/alliance/*` + `state` | `test_alliance.py` (66+) | ✅ MVP complete | Combat-/Diplomatie-Deep-Hooks post-Beta |
| **Planet Evolution** | `planet_evolution/` | `/planet-evolution` | `/api/planets/<id>/*` + `state` | `test_planet_evolution*.py` | ✅ | ⚠️ Client `reloadCurrentPage` (GC-512A) |
| **Ranking** | `ranking.py`, `scoring.py` | `/ranking` | `GET /api/ranking` | `test_ranking.py` | ✅ | — |
| **Admin** | `admin.py`, `admin_api.py` | `/admin`, `admin.js` | `/api/admin/*` | `test_admin_*` | ✅ | ⚠️ Legacy Forms parallel |
| **Support** | `support.py` | Options/Support UI | `/api/support/*`, admin support | — | ✅ | Mehr pytest optional |
| **Options** | `options.py`, `account_email.py` | `/options`, `options.js` | `/api/options/*` | `test_options.py`, `test_account_email` | ✅ | — |
| **Empire / Command Map** | `planet_evolution/command_map.py`, `world_map.py` | `/empire` | `/api/command-map/*` | `test_command_map*.py`, `test_world_map.py` | ✅ | GC-598 mission actions backlog |
| **Inventory** | `inventory.py`, `inventory_loot.py` | `/inventory` | `/api/inventory/*` | `test_inventory*.py` | ✅ | — |
| **Auction House** | `auction_house.py` | `/auction-house` | `/api/auction-house/*` | `test_auction_house.py` | ✅ | — |
| **Vote Center** | `vote_rewards.py` | `/vote-center` | `/api/vote/*` | `test_vote_rewards.py` | ✅ | — |
| **Galactic Politics** | `galactic_directives/`, `galactic_diplomacy/` | `/galactic-politics` | `/api/galactic-politics/*` | `test_galactic_*.py` | ✅ | — |
| **Referrals** | `referrals.py` | `/referrals` | `/api/referrals/*` | `test_referrals.py` | ✅ | — |
| **Meta content** | news, chronicles, hall-of-fame, records | `/news`, … | read APIs | various | ✅ | — |

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

## Doc-Reality Gaps (offen)

| Doc | Problem | Status |
|-----|---------|--------|
| `BUILDINGS_SYSTEM.md` / `RESEARCH_SYSTEM.md` | Cancel refunds, Kosten/Zeit | ✅ Reality-Sync 2026-06-24 |
| `ECONOMY_SYSTEM.md` | Storage 150k, fuel_storage, loot floors | ✅ Reality-Sync 2026-06-24 |
| `EffectResolver` build time | `power_build_seconds` (GC-850A) | ✅ Reality-Sync 2026-06-24 |
| Shipyard envelope | `{ok,data}` statt `{ok,state}` | ⚠️ GC-512D backlog |
| Alliance backend + UI + PJAX | MVP complete (GC-AL-MVP-01…09) | ✅ Rollen, Rekrutierung, Spenden, Projekte, Boni, Tests, Docs |

Historisches GC-601 Audit: [GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md](GC-601B_DOCUMENTATION_CONSISTENCY_SYNC.md) (closed).

---

## GC-700 Readiness (Combat)

### Vorhanden

- **Resolver:** `game/combat.py` — `simulate_battle()`, loot (`apply_combat_loot`), debris (`spawn_combat_debris_at_planet`), reports (`publish_attack_combat_report`)
- **Simulator (GC-700A):** `game/combat_simulator.py` — `/combat-simulator`, `POST /api/combat-simulator/run` (Monte-Carlo, no DB)
- **Modelle:** `game/combat_models.py` — Stats für Schiffe + Defense, Rapid Fire
- **Integration:** `game/fleet.py` — Attack-Arrival: simulate → losses → debris → ranking → loot → inbox
- **Defense-Anbindung:** `planet_defense` in `simulate_battle` / `split_defender_losses`
- **Effects:** `EffectResolver` Waffen/Schild/Panzer-Boni
- **Spy/Intel:** Tier-5 Defense in `spy.py`
- **Tests:** `tests/test_combat.py` (36+), `tests/test_combat_simulator.py`, Fleet-Spy/Attack in `test_fleet.py`
- **Docs:** [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) aktuell (GC-500–510, GC-700A)

### Fehlt / GC-700 sinnvoller Scope

| Item | Priorität | Hinweis |
|------|-----------|---------|
| Recycler / Debris-Harvest-Mission | — | ✅ GC-800A/B (`recycle` mission) |
| Fleet Logistics Collect | — | ✅ GC-900B: `batch_type` + N× `mission=collect` |
| Fleet Logistics Distribute | — | ✅ GC-900D/E |
| Combat-Balancing / neue Missionen | P2 | Simulator ✅ — keine Resolver-Duplikate |
| PvP-Randfälle / Report-UX | P2 | Messages UI vorhanden |
| Dedizierte Combat-Admin-Tools | P3 | Simulator Admin-Modus (Monte-Carlo, Effizienz-Tabelle) |

### Risiken

- Doppel-Implementierung von `simulate_battle` oder parallele Fleet-State-Queues — **Simulator nutzt nur `simulate_battle`**
- Frontend-Kampf-Math (verboten GC-000) — **Simulator POST liefert Ergebnis; UI rechnet nicht**
- Attack-Tick Idempotenz bei Retries (`fleet.py` markiert `failed` — dokumentiert in COMBAT_SYSTEM)

### Empfohlener Scope für GC-700 (Rest)

**Nicht:** Combat-Engine von Null.

**Ja (Beispiele, je nach Product-Priorität):**

1. Report-UX / PvP-Randfälle (kein Resolver-Neubau)
2. Combat v2 nur wenn: neue Missionstypen oder Resolver-Regeländerungen — max. 3–5 Dateien, Tests in `test_combat.py`

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
| GC-700 Combat | ✅ GC-700A Simulator — siehe [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) |
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
