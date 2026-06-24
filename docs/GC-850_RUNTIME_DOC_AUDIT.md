# GC-850 — Runtime ↔ Documentation Audit

> **Typ:** Audit only — **keine Fixes**, keine Refactorings.  
> **Stand Audit:** 2026-06-24 · Code-Ref: `main` @ `4912e05`  
> **Nachfolger:** [GC-850A](GC-850A_BUILD_TIME_MISMATCH.md) (Build-Time Entscheidung) · GC-851 (Meta-Guard, danach)

---

## Ziel

```text
Master Docs → BALANCE_ANCHORS → Runtime Owner → Tests
```

Für jede Kern-Domäne feststellen:

| Status | Bedeutung |
|--------|-----------|
| **OK** | Docs, Anker und Runtime stimmen überein (oder bewusst dokumentierte Abweichung) |
| **DOC OK / CODE FALSCH** | Docs/Design sind kanonisch; Runtime weicht ab |
| **CODE OK / DOC FALSCH** | Runtime ist korrekt; Docs sind veraltet/falsch |
| **DOC GAP** | Runtime existiert; Master-Doc beschreibt Formel/Verhalten nicht |
| **DOC INCONSISTENT** | Zwei Master-Docs widersprechen sich (ohne klaren Owner) |

---

## Audit-Methode

1. Master-Doc lesen (P0-Verfassung zuerst)
2. `BALANCE_ANCHORS.md` / `GC_ANCHOR_TABLES_X1.md` (falls Domäne abgedeckt)
3. Runtime-Owner in `game/*` trace'n (enqueue → cost/time → cancel/refund)
4. Contract-Tests (`test_gc821_*`, `test_gc831_*`, `test_production_formula`, …) als Regression-Signal

**Nicht:** Ticket-Docs GC-5xx/6xx als Wahrheit — nur Master + Anker + Code.

---

## Executive Summary

| Kategorie | Anzahl |
|-----------|--------|
| OK | 12 |
| DOC OK / CODE FALSCH | **1** (Build-Time vs GC-821 Design) |
| CODE OK / DOC FALSCH | **2** (Defense Refund, Loot Unit-Floors) |
| DOC GAP | **4** |
| DOC INCONSISTENT | **2** |

**Kritischer Befund:** Nur **ein** bestätigter Mechanik-Mismatch zwischen Design-Ankern und Runtime (Build-Zeit). Zusätzlich **zwei** veraltete Domänen-Docs (Defense, Economy-Loot) und **Architektur-Inkonsistenzen** (AJAX-Envelope), die kein Balance-Problem sind, aber Cursor/System-Bugs begünstigen.

---

## P0 — Verfassung (systemischer Schaden)

### CORE_ARCHITECTURE.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Planet Scope (`get_context_planet`) | **OK** | `players.active_planet_id` → `repository.get_context_planet()` |
| Queue Finish-Before-Mutate | **OK** | `queue_engine.finish_due_work_once` |
| No Duplicate Math (Regel 16) | **OK** | Production/Research delegieren an kanonische Module |
| §7 AJAX Action Contract | **DOC INCONSISTENT** | Behauptet universell `{ ok, state }`. **Ausnahme:** Shipyard + Teile Fleet → `{ ok, data }` via `fleet_ok()` (`app.py`). Korrektur in [STATE_AJAX.md](STATE_AJAX.md), **nicht** in CORE. |
| §17 Live-State Owner | **OK** | `app.py` + `logic.py` + `live_state.py` (Sync 2026-06-24) |

### STATE_AJAX.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Diet poll vs `include_panel=1` | **OK** | Entspricht `read_player_live_state_for_poll` / `refresh_player_live_state` |
| Timer completion | **OK** | `refreshGameState` → `include_panel=1`, kein Full-Reload |
| Planet switch | **OK** | `skipGameState` + `skipPolling` + HUD-only `applyActionState` |
| Shipyard `{ ok, data }` Ausnahme | **OK** | Explizit dokumentiert (GC-512D backlog) |

### PLANET_SCOPE.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| `active_planet_id` in DB | **OK** | Kein Session-Planet |
| `POST /api/planets/active` | **OK** | `include_panel=False`, `action_slim` im Live-Pfad |
| Homeworld nur Fallback | **OK** | Resolver-Verhalten |

### QUEUE_STATE_RULES.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Finish before mutate | **OK** | |
| Reschedule after cancel | **OK** | Build/Research/Shipyard/Defense |
| GC-831 Refund 100/50/0 | **OK** | `game/queue_refund.py` |
| Cost snapshot priority (076) | **OK** | Build/Research bevorzugen Row-Snapshot |
| **Widerspruch DEFENSE_SYSTEM** | **DOC INCONSISTENT** | QUEUE_STATE sagt GC-831; DEFENSE_SYSTEM sagt noch 60 % → siehe P2 Defense |

---

## P1 — Balance & Economy

### BALANCE_ANCHORS.md + GC_ANCHOR_TABLES_X1.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Production bases/exponents | **OK** | `production_formula.LEVEL_GROWTH` |
| Upgrade costs `power_upgrade_cost` | **OK** | `buildings.get_upgrade_cost()` |
| Research anchors GC-825 | **OK** | `research_base_time_seconds`, `research_upgrade_cost` |
| Refund rules | **OK** | `queue_refund.py` |
| Starter resources GC-836 | **OK** | `DEFAULT_GAME_SETTINGS` |
| Build-Zeit Design vs Live | **DOC OK / CODE FALSCH** | Siehe Mechanik #1 unten |
| Minen-ROI L20–L120 | **OK** (mit Hinweis) | Ziel-Anker für Ferronit; Crytite/BZ weichen ab — in Anker-Doc vermerkt |

### ECONOMY_SYSTEM.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Storage 150k / ×1.75 | **OK** | `economy_balance` + `EffectResolver` |
| `fuel_storage` Pflicht | **OK** | `fuel_cells_storage_capacity()` |
| Klima-Overlay `directive_modifier` | **OK** | `prod_overlay_factor()` |
| Resource-Loot Floors 12k–30k | **OK** | `LOOT_RESOURCE_FLOOR_*` in `economy_balance` |
| **Ship/Defense-Loot Floors 12k–30k** | **CODE OK / DOC FALSCH** | Code: `LOOT_UNIT_FLOOR_MIN/MAX = 5_000/10_000` in `inventory_loot.py` |
| Military ×1.25 | **DOC GAP** | GC-821 sagt „×1.25“ — Werte sind **in** `fleet_defs`/`defense_defs` eingebacken; `scaled_military_cost()` **ungenutzt** |

### BUILDINGS_SYSTEM.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Kosten `power_upgrade_cost` | **OK** | |
| Build-Zeit Legacy-Pfad | **OK** | Dokumentiert als Legacy; Design-Kurve separat |
| GC-831 Cancel | **OK** | |
| `queue_limit` Default 5 | **OK** | |

### RESEARCH_SYSTEM.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| GC-825 Zeit/Kosten | **OK** | `EffectResolver.get_research_time_seconds` |
| Combat/Fleet-Tech aktiv | **OK** | `simulate_battle`, `fleet.py` |
| GC-831 Cancel | **OK** | |

### PRODUCTION_FORMULA_SYSTEM.md

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Snapshot Slot 9 | **OK** | |
| `directive_modifier` Klima+GD+Diplomacy | **OK** | |

---

## P2 — Mechanik-Audit (vorgegebene Reihenfolge)

### 1. Build-Time ⚠️

| Status | **DOC OK / CODE FALSCH** (relativ zu GC-821 Design-Kurve) |
|--------|----------------------------------------------------------|
| **Design** | `economy_balance.power_build_seconds()` — `TIME_K × level^exponent` |
| **Runtime** | `EffectResolver.get_build_time_seconds()` → `BUILD_TIME_BASE × BUILD_TIME_FACTOR^(L-1)` ÷ Speed-Boni |
| **Docs** | `BUILDINGS_SYSTEM.md`, `BALANCE_ANCHORS.md`, `EFFECTS.md` beschreiben beide Pfade ehrlich |
| **Tests** | `test_gc821_economy_rebalance` prüft `power_build_seconds`; **kein** Test erzwingt Resolver-Wiring |
| **Fix-Ticket** | [GC-850A](GC-850A_BUILD_TIME_MISMATCH.md) |

### 2. Shipyard

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Kosten | **OK** | `fleet_defs.build_cost` direkt, kein Runtime-Multiplier |
| Bauzeit | **DOC GAP** | `shipyard._effective_build_seconds`: `build_seconds × 0.9^(yard-1) ÷ shipyard_speed` — **nicht** in FLEET_SYSTEM/BUILDINGS/BALANCE_ANCHORS |
| Cancel Refund | **OK** | `shipyard_queue.cancel_queue_job` → `queue_refund.refund_from_stored_costs` |
| API Envelope | **DOC INCONSISTENT** | `{ ok, data }` — STATE_AJAX ✅, CORE_ARCHITECTURE §7 ❌, AJAX_PJAX ❌ |
| BALANCE_ANCHORS Abdeckung | **DOC GAP** | Shipyard nicht in Anker-Tabellen |

### 3. Defense

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Kosten | **OK** | `defense_defs.unit_build_cost` — raw table values |
| Bauzeit | **DOC GAP** | `defense.py` analog Shipyard (`build_seconds` × Fabrik-Faktor) — DEFENSE_SYSTEM nennt Formel grob, nicht verifiziert gegen Code-Zeile |
| **Cancel Refund 60 %** | **CODE OK / DOC FALSCH** | `DEFENSE_SYSTEM.md` L125–134: „60 %“ / `CANCEL_REFUND_RATIO`. **Runtime:** `cancel_defense_job` → `refund_from_stored_costs` = GC-831 **100/50 %** |
| QUEUE_STATE vs DEFENSE | **DOC INCONSISTENT** | |

### 4. Fleet Travel

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| `calculate_flight_seconds` | **OK** | `(35000/speed) × √(dist/10)` — FLEET_SYSTEM.md |
| `navigation_tech` / `engine_tech` | **OK** | `_fleet_speed_multiplier` → `calculate_fleet_speed` |
| `fuel_efficiency` | **OK** | `_fuel_efficiency_factor_for_fleet` → `calculate_fuel_cost` |
| BALANCE_ANCHORS | **DOC GAP** | Keine Flugzeit-Ankertabelle (bewusst außerhalb GC-820/821) |

### 5. Expedition

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Event engine | **OK** | `expedition_events.py` — FLEET_SYSTEM.md sehr detailliert |
| Loot cap | **OK** | `calculate_expedition_loot_cap` — cargo × 50 |
| BALANCE_ANCHORS | **DOC GAP** | Expedition nicht in Anker-Docs |
| Vollständige Gewichts-Audit | **OK** | `expedition_event_weight_audit()` + Tests GC-620J |

### 6. Combat

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| `simulate_battle` | **OK** | COMBAT_SYSTEM.md ↔ `combat.py` |
| Tech modifiers | **OK** | `EffectResolver.get_combat_modifiers` |
| Rapid fire cap 64 | **OK** | COMBAT_SYSTEM dokumentiert |
| BALANCE_ANCHORS | **N/A** | Combat nicht in Economy-Ankern |

### 7. Planet Evolution

| Prüfpunkt | Status | Detail |
|-----------|--------|--------|
| Scope Planet vs Account | **OK** | PLANET_EVOLUTION vs RESEARCH_SYSTEM |
| Planet-Tech Zeit/Kosten | **DOC GAP** | `compute_planet_research_time/cost` nutzt **Legacy** `cost_factor^level` / `tier_mult` — **nicht** GC-825. PLANET_EVOLUTION.md beschreibt **keine** Formel |
| Abgleich BALANCE_ANCHORS | **N/A** | Planet-Tech bewusst außerhalb Economy-Anker |
| Version-Header v1.5.3 | **CODE OK / DOC FALSCH** | Meta-Drift (→ GC-851) |

---

## Vollständige Abweichungsliste (Fix-Backlog)

| ID | Priorität | Domäne | Status | Owner-Modul | Fix-Ticket |
|----|-----------|--------|--------|-------------|------------|
| GC850-01 | **P1** | Build-Time | ~~DOC OK / CODE FALSCH~~ **✅ GC-850A** | `effect_resolver.get_build_time_seconds` | — |
| GC850-02 | **P2** | Defense Cancel % | ~~CODE OK / DOC FALSCH~~ **✅ GC-850B** | `DEFENSE_SYSTEM.md` | — |
| GC850-03 | **P1** | Loot Unit-Floors | ~~CODE OK / DOC FALSCH~~ **✅ GC-850B** | `ECONOMY_SYSTEM.md` | — |
| GC850-04 | **P0** | AJAX Envelope | ~~DOC INCONSISTENT~~ **✅ GC-850B** | CORE + AJAX_PJAX | — |
| GC850-05 | **P2** | Shipyard Bauzeit | DOC GAP | `shipyard.py` | Backlog (doc) |
| GC850-06 | **P2** | Planet-Tech Formeln | DOC GAP | `planet_research.py` | Backlog (doc) |
| GC850-07 | **P1** | Military ×1.25 | ~~DOC GAP~~ **✅ GC-850B** | `fleet_defs`/`defense_defs` | — |
| GC850-08 | **Meta** | Version headers | CODE OK / DOC FALSCH | PLANET_EVOLUTION, FLEET, … | GC-851 |

**Nicht in Backlog (bewusst):**

- Crytite/Brennzellen ROI weicht von Ferronit-Ankern ab — Design, in BALANCE_ANCHORS vermerkt
- `scaled_military_cost()` ungenutzt — tote Helper-Funktion, kein Runtime-Bug

---

## Tests als Audit-Signal

| Domäne | Tests | Deckung |
|--------|-------|---------|
| Production | `test_production_formula.py` | ✅ Formel |
| Economy GC-821 | `test_gc821_*` | ✅ Kosten, `power_build_seconds` (Design only) |
| Research GC-825 | `test_gc825_*` | ✅ Account-Forschung |
| Refunds GC-831 | `test_gc831_queue_refund.py` | ✅ inkl. Defense/Shipyard |
| Build-Time Runtime | — | ❌ **Kein** Test Resolver == `power_build_seconds` |
| Fleet speed/fuel | `test_fleet.py`, `test_effects.py` | ✅ teilweise |
| Combat | `test_combat.py` | ✅ |
| Doc meta sync | — | ❌ GC-851 geplant |

---

## Akzeptanzkriterien (GC-850)

- [x] P0–P2 Audit-Tabelle vollständig
- [x] Jede Abweichung mit Status + Owner + Fix-Ticket-Referenz
- [x] **Keine** Code-Fixes in GC-850
- [x] Build-Time als GC-850A ausgelagert
- [ ] GC-851 erst nach GC-850A/B (User-Entscheidung)

---

## Ausgabe (GC-850)

### Root Cause

Monatelange Parallel-Entwicklung (GC-7xx/8xx Reworks) ohne durchgängigen Runtime↔Doc-Sync. Docs-Sync 2026-06-24 schloss die größte Lücke; verbleibende Abweichungen sind **klein in Anzahl**, aber **Build-Time ist ein echter Design/Runtime-Split**.

### Changed Files

- `docs/GC-850_RUNTIME_DOC_AUDIT.md` (dieses Dokument)
- `docs/GC-850A_BUILD_TIME_MISMATCH.md` (Entscheidungs-Ticket)

### Tests

Keine (Audit-only).

### Ergebnis

**1** bestätigter Mechanik-Mismatch (Build-Time), **2** veraltete Domänen-Docs, **4** Doc-Gaps, **2** Master-Doc-Inkonsistenzen. Keine versteckte Flut von 5–10 Altlasten — der GC-821/825/831-Sync hat den Großteil bereits bereinigt.

---

## Referenz-Docs

- [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)
- [WORKFLOW.md](WORKFLOW.md)
