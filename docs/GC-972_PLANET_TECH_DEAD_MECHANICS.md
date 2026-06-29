# GC-972 — Planet-Tech: Tote Mechanics reparieren

> **Epic:** EPIC-05 Planet Evolution  
> **Status:** ✅ **Abgeschlossen (A–D)** — Dead-Hook-Fix; **E/F deferred** (Design-Entscheidung, kein Halb-Implement)  
> **Stand:** Jun 2026  
> **Owner:** `game/planet_evolution/mechanics.py` (Compile) + jeweilige Consumer-Module

**Leitplanke:** Kaputte/tote Hooks fixen. Keine Fantasy-Imperiums-Boni, keine neuen Tech-Keys, keine Balance-Neuerfindung.

---

## Epic-Status

| Ticket | Titel | Status | Tests |
|--------|-------|--------|-------|
| **GC-972A** | `industry_t4` Requirements fix | ✅ Done | `test_planet_research_any_requirement_or_logic`, Queue-Tests |
| **GC-972B** | `chain_output_bonus` in Economy | ✅ Done | 4 Chain-Output-Tests |
| **GC-972C** | `policy_unlock` / `policy_tier` | ✅ Done | 6 Policy-Gate-Tests |
| **GC-972D** | `event_pool` in Event-Engine | ✅ Done | 3 Event-Pool-Tests |
| **GC-972E** | Experimental + `risk_json` | ⏸ **Deferred** — siehe unten | — |
| **GC-972F** | Conversion-Queue | ⏸ **Deferred** → **GC-973** | — |

**Gesamt:** `tests/test_planet_evolution.py` + `tests/test_planet_evolution_dashboard.py` — **49 passed** (Jun 2026).

**Nachfolger:** [GC-974 — Balancing & Identity](GC-974_PLANET_EVOLUTION_BALANCING.md) · [GC-973 — Conversion Queue](GC-973_PLANET_CONVERSION_QUEUE.md)

---

## Erledigte Sub-Tickets (Kurzbericht)

### GC-972A — `industry_t4_mass_foundry` erreichbar

**Root Cause:** Requirements verlangten beide T3-Pfade nach irreversiblem `mining_path`.

**Changed Files:** `game/planet_evolution/requirements.py` (`planet_research_any`), `migrations/086_pe_industry_t4_requirements.sql`, `migrations/017_planet_evolution_definitions_seed.sql`, `tests/test_planet_evolution.py`

**Ergebnis:** Ein beliebiges Industry-T3 reicht; T4 queuebar.

---

### GC-972B — `chain_output_bonus`

**Root Cause:** Flag kompiliert, `economy` las nur `chain_output_mult`.

**Changed Files:** `game/planet_evolution/economy.py` (`_chain_output_bonus_factor`), `tests/test_planet_evolution.py`

**Ergebnis:** Per-Chain +15 % (0.15) für `orbital_t2_zero_g_foundry` im Spezialressourcen-Tick.

---

### GC-972C — Policy-Freischaltung

**Root Cause:** `policy_unlock:*` / `policy_tier` kompiliert, `activate_policy` und Dashboard ignorierten Flags.

**Changed Files:** `game/planet_evolution/policies.py` (neu), `service.py`, `dashboard.py`, `locales/*.json`, `tests/test_planet_evolution.py`

**Ergebnis:** `mandatory_overtime` nur mit Research/Spec-Unlock; Dashboard zeigt `pe_policy_locked_by_research` / `pe_policy_tier_locked`. **GC-974A:** Cap-Semantik entfernt — `policy_tier` unlock-only (siehe [GC-974A_POLICY_TIER.md](GC-974A_POLICY_TIER.md)).

---

### GC-972D — `event_pool`

**Root Cause:** `enable_event_pool` aus Research nicht in Flags; Event-Engine las nur Spec-`pool_tags`.

**Changed Files:** `game/planet_evolution/mechanics.py` (`enable_event_pool` → `event_pool:*`), `game/planet_evolution/events.py` (Pool-Adapter), `locales/*.json` (ehrlicher Breakthrough-Hinweis), `tests/test_planet_evolution.py`

**Ergebnis:** `science_t3_breakthrough_lab` ermöglicht `science_breakthrough` ohne `science_nexus`-Spec; Adapter: `pool:{name}`, `event_key == name`, `{name}_*` Prefix.

---

## GC-972E — Experimental + Risiko ⏸ DEFERRED

### Product-Entscheidung (Jun 2026)

- **Kein** schnelles Failure-/Risk-System innerhalb GC-972.
- `experimental_enabled`, `risk_json`, `risk_event:*` bleiben **vorbereitet** (Compile teilweise), **ohne Runtime-Consumer**.
- UI/Locale: ehrlich — *„Experimentelle Risiko-Mechanik vorbereitet / folgt später.“*
- **Option A** (Consumer in `failures.py` / Research-Finish-Roll) → **eigenes Ticket nach GC-973**, falls Product Experimental-Linie behalten will.

### Betroffene Techs (unverändert im Seed)

| Tech | Mechanics | risk_json |
|------|-----------|-----------|
| `science_t5_experimental_gate` | `enable_experimental` | `experimental_failure: 0.08` |
| `experimental_t1_dark_matter` | `enable_experimental` | `experimental_failure: 0.10` |
| `industry_t5_overdrive` | `risk_event:forge_reactor_overload` (unparsed) | `experimental_failure: 0.05` |

### Offene Compile-Lücken (bewusst)

| Lücke | Geplant in |
|-------|------------|
| `risk_json` Research-Row → `risk_modifiers` | Post-GC-972E |
| `risk_event` in mechanics_json | Post-GC-972E |

### UI/Locale (GC-972 Abschluss)

`desc_pe_*` und `pe_tech_*` für Experimental-Techs entschärft — kein Versprechen aktiver Fehlschlag-Chance. Policy-Teil von `industry_t5_overdrive` bleibt korrekt (972C live); Reaktor-Risiko-Event deferred.

---

## GC-972F — Conversion ⏸ DEFERRED → GC-973

### Product-Entscheidung (Jun 2026)

- Conversion-Queue wird **nicht** in GC-972 implementiert.
- Folge-Epic: **[GC-973_PLANET_CONVERSION_QUEUE.md](GC-973_PLANET_CONVERSION_QUEUE.md)** — „Planet Conversion Queue / Special Resource Processing“.
- `industry_t1_automation` / `industry_t4_mass_foundry`: UI/Locale beschreiben Conversion als **vorbereitet**, nicht live.
- `conversion_batch_bonus` Parsing → **GC-973A**.

### Problem (unverändert)

- Tabelle `planet_conversion_queue` (Migration `016`), kein Engine-Modul
- `queue_limits.conversion` wird gesetzt, aber nicht konsumiert

---

## Ursprüngliches Problem (Kontext)

18 Planet-Techs in `pe_research_definitions` (Seed `017`) versprechen Effekte über `mechanics_json` / `risk_json`. Nach GC-972A–D sind die **P0/P1 Dead-Hooks** behoben; verbleibende Lücken sind **bewusst deferred** mit ehrlicher Copy.

| Tech | Mechanik | Status nach GC-972 |
|------|----------|-------------------|
| `industry_t4_mass_foundry` | Req + `conversion_batch_bonus` | Req ✅; Conversion → GC-973 |
| `orbital_t2_zero_g_foundry` | `chain_output_bonus` | ✅ Live |
| `governance_t1_civil_admin` | `policy_tier` | ✅ Live (972C) |
| `industry_t5_overdrive` | `enable_policy:mandatory_overtime` | ✅ Policy live; `risk_event` → 972E |
| `science_t3_breakthrough_lab` | `enable_event_pool` | ✅ Live (972D) |
| `science_t5_experimental_gate` | experimental + risk | ⏸ 972E |
| `experimental_t1_dark_matter` | experimental + risk | ⏸ 972E |
| `industry_t1_automation` | `unlock_queue.conversion` | ⏸ GC-973 |

---

## Querschnitt — Compile-Lücken (Rest)

| Lücke | Fix in |
|-------|--------|
| `conversion_batch_bonus` nicht geparst | GC-973A |
| `risk_json` Research-Row nicht gemerged | GC-972E (später) |
| `risk_event` in mechanics_json nicht geparst | GC-972E (später) |
| `enable_event_pool` in mechanics_json | ✅ 972D |

---

## Explizit out of scope (GC-972)

- Neue Imperiums-Boni / neue Tech-Keys
- Account-Forschung (`game/research.py`)
- Balance-Tuning über Seed-Kosten/Zeiten
- UI-Redesign Planet-Evolution-Seite
- Conversion-Engine (→ GC-973)
- Experimental-Failure-Rolls (→ post-972E)

---

## Referenz-Docs

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) — GC-973
- [GC-973_PLANET_CONVERSION_QUEUE.md](GC-973_PLANET_CONVERSION_QUEUE.md)

---

## Test-Strategie (Epic A–D — erfüllt)

| Ticket | Test |
|--------|------|
| 972A | `test_planet_research_any_requirement_or_logic` |
| 972B | Chain output delta (4 Tests) |
| 972C | Policy gate (6 Tests) |
| 972D | Event pool compile + pick (3 Tests) |

**Philosophie:** Grüne Tests = echter Runtime-Effekt, nicht nur Flag in DB.
