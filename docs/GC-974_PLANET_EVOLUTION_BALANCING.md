# GC-974 — Planet Evolution Balancing & Identity

> **Epic:** EPIC-05 Planet Evolution  
> **Status:** 📋 Analyse (Alpha-Balancing-Pass) — **keine Seed-/Code-Änderungen in diesem Ticket**  
> **Voraussetzung:** GC-972A–D ✅, GC-972E/F deferred, GC-973 geplant  
> **Stand:** Jun 2026

---

## Ziel

Jede Planet-Tech soll sich **spürbar unterschiedlich** anfühlen. Dieser Report klassifiziert den **Ist-Zustand nach Dead-Hook-Fix** und priorisiert gezielte Nachschärfung — statt später überall kleine Einzelpatches.

**Nicht in Scope:** Conversion-Engine (GC-973), Experimental-Failure-Rolls (post-972E), neue Tech-Keys.

---

## Methodik

Für jede der **18 Planet-Techs** (Seed `017`):

| Kriterium | Quelle |
|-----------|--------|
| **XP** | `25 + tier × 15` (`compute_planet_research_reward_xp`) |
| **Gameplay-Nutzen** | Runtime-Consumer in `game/planet_evolution/` (economy, events, policies, planet_research, discoveries, mechanics compile) |
| **Sichtbarer Nutzen** | Hero/Dashboard/Economy/Politik/Events — was der Spieler ohne Wiki sieht |
| **Priorität** | 🟢 stark · 🟡 mittel · 🔴 schwach/deferred · ⚠️ Design-Risiko |

**Legende Gameplay-Nutzen:** `hoch` = messbarer Server-Effekt · `mittel` = situativ/Pfad · `gering` = fast nur XP oder vorbereitet · `—` = kein Runtime-Effekt

---

## Tech-Matrix (Ist-Zustand)

| Tech (DE) | Key | Tier | XP | Mechanik (Seed) | Gameplay-Nutzen | Sichtbarer Nutzen | Prio |
|-----------|-----|-----:|---:|-----------------|-----------------|-------------------|-----|
| Industrie-Automatisierung | `industry_t1_automation` | 1 | 40 | `unlock_queue.conversion:1` | **gering** — Flag gesetzt, **kein Consumer** (GC-973) | niedrig (Copy ehrlich) | 🔴 |
| Bergbau-Pfad | `industry_t2_mining_path` | 2 | 55 | Pfadwahl `orbital_mining` / `deep_core` | **hoch** — gate für ganzen Industry-Zweig | mittel (Choice-UI) | 🟢 |
| Orbitalraffinerie | `industry_t3_orbital_refinery` | 3 | 70 | Chain `refined_ferronit` | **hoch** — ~120/h Spezialressource | hoch (Economy-Chip) | 🟢 |
| Mantel-Tap | `industry_t3_mantle_tap` | 3 | 70 | Chain `mantle_alloy` | **hoch** — ~60/h Spezialressource | hoch | 🟢 |
| Massengießerei | `industry_t4_mass_foundry` | 4 | 85 | `conversion_batch_bonus:1` | **gering** — nicht geparst (GC-973) | niedrig | 🔴 |
| Industrie-Overdrive | `industry_t5_overdrive` | 5 | 100 | `enable_policy:mandatory_overtime` | **hoch** — Policy +20 % Ketten-Output | hoch (Politik) | 🟢 |
| Feld-Labore | `science_t1_field_labs` | 1 | 40 | `planet_research_speed_flag:0.10` | **hoch** — −10 % Forschungszeit global | mittel (kürzere Queue) | 🟢 |
| Quanten-Kartographie | `science_t2_quantum_mapping` | 2 | 55 | Chain `quantum_data` | **hoch** — ~40/h + Spec-Import | hoch | 🟢 |
| Breakthrough-Lab | `science_t3_breakthrough_lab` | 3 | 70 | `enable_event_pool:science_breakthrough` | **mittel** — Event-Pool (RNG, 3 %/Tag) | mittel (Events-Tab) | 🟡 |
| Experimentelles Tor | `science_t5_experimental_gate` | 5 | 100 | `enable_experimental` + risk | **gering** — Flag only (972E deferred) | niedrig (ehrliche Copy) | 🔴 |
| Plasma-Harness | `energy_t2_plasma_harness` | 2 | 55 | Chain `dark_plasma` | **mittel** — nur mit Trait `plasma_winds` | hoch wenn Trait | 🟡 |
| Biomasse-Extraktion | `ecology_t1_biomass` | 1 | 40 | Chain `living_crystal` | **mittel** — keine Building-Req, früh erreichbar | mittel | 🟡 |
| Markt-Protokolle | `trade_t2_market_protocols` | 2 | 55 | `trade_route_bonus:0.10` | **mittel** — +10 % Routen-Erlös | niedrig (Routen wenig sichtbar) | 🟡 |
| Zivilverwaltung | `governance_t1_civil_admin` | 1 | 40 | `unlock_policy_tier:1` | Freischaltung Tier-1-Policies (kein Cap) | mittel | ✅ GC-974A |
| Ruinen-Vermessung | `ancient_t1_ruins_survey` | 1 | 40 | Chain `ancient_alloy` | **mittel** — Trait `ancient_ruins` nötig | hoch wenn Trait | 🟡 |
| Dunkle Materie | `experimental_t1_dark_matter` | 1 | 40 | `enable_experimental` + risk | **gering** — 972E deferred | niedrig | 🔴 |
| Befestigung | `military_t2_fortification` | 2 | 55 | Chain `phase_crystal` | **mittel** — `defense_factory` ≥ 2 | mittel | 🟡 |
| Zero-G-Gießerei | `orbital_t2_zero_g_foundry` | 2 | 55 | `chain_output_bonus` +15 % `refined_ferronit` | **hoch** — +15 % auf Orbital-Kette | hoch (Prod-Badge) | 🟢 |

---

## Pfad-Analyse: Industry `mining_path`

| Pfad | Techs | Stärke | Schwäche |
|------|-------|--------|----------|
| **Orbital** (`orbital_mining`) | T3 Raffinerie, `orbital_t2_zero_g_foundry`, T4 | **Zusätzlicher Output-Bonus**, eine starke Export-Ressource (`refined_ferronit`), Synergie mit `forge_world` | Nur eine Spezialisierungs-Exportlinie |
| **Deep Core** (`deep_core`) | T3 Mantel-Tap, T4 | Alternative Ressource (`mantle_alloy`), Spec `forge_world` T2 chain | **Kein** analoger T2-Bonus-Tech |

**Tendenz:** Orbital-Pfad wirkt **stärker** (mehr live Hooks pro Tech). Deep Core braucht Balancing-Liebe (eigenen Mid-Tier-Bonus oder stärkere `mantle_alloy`-Basisrate).

**Must-Pick auf Industry-Linie:** T2-Pfadwahl ist unvermeidlich; innerhalb Orbital ist **Zero-G-Gießerei** nahezu Pflicht nach Raffinerie.

---

## Pfad-Analyse: Science-Linie

Linear: T1 → T2 → T3 → T5 (kein T4 im Seed).

| Stufe | Rolle heute |
|-------|-------------|
| T1 Feld-Labore | **Früh-Must-Pick** für Tech-Rusher (+10 % Speed, spürbar) |
| T2 Quanten-Kartographie | Chain + Spec-Voraussetzung (`quantum_data`) |
| T3 Breakthrough-Lab | Event-Content (mittlere RNG-Frucht) |
| T5 Experimentelles Tor | Nur XP + Flag — **kein** Risiko-Gameplay |

**Lücke:** Kein Science-T4 → T5 fühlt sich wie Sprung an; Balancing könnte T4 als Brücke oder T5-Wert bis 972E aufschieben.

---

## Must-Picks & Schwachpicks

### Verdacht Must-Picks (Alpha)

1. **`science_t1_field_labs`** — beste Early-ROI für Planet-Tech-Spam (Speed).
2. **`industry_t2_mining_path` → orbital** — mehr live Boni als Deep Core.
3. **`orbital_t2_zero_g_foundry`** — klarer +15 % auf Haupt-Industry-Output (nach Orbital-Pfad).
4. **`industry_t5_overdrive`** — Endgame-Industrie: +20 % alle Ketten via Policy (wenn freischaltbar).

### Verdacht Schwachpicks / „nur XP“

1. **`industry_t1_automation`** — Conversion tot (GC-973).
2. **`industry_t4_mass_foundry`** — erreichbar seit 972A, aber Batch-Bonus tot.
3. **`science_t5_experimental_gate`**, **`experimental_t1_dark_matter`** — Experimental deferred.
4. **`governance_t1_civil_admin`** — siehe Paradox unten.

### Situativ (Trait / Building)

- `energy_t2_plasma_harness`, `ancient_t1_ruins_survey`, `experimental_t1_dark_matter` — ohne Trait kaum relevant.
- `military_t2_fortification` — spät (Defense Factory 2).
- `trade_t2_market_protocols` — nur wertvoll bei aktivem Routen-Spiel.

---

## ~~Design-Risiko~~ ✅ GC-974A: `governance_t1_civil_admin`

**Stand:** GC-974A — `policy_tier` ist **unlock-only**, kein Cap.

**Semantik:** `unlock_policy_tier: N` setzt `flags.policy_tier` (max-Merge). Tier-2+-Policies werden **nicht** durch dieses Flag gesperrt. Tier-1-Policies erfordern `policy_tier >= 1`, mit Legacy-Bypass wenn das Flag fehlt.

→ Siehe [GC-974A_POLICY_TIER.md](GC-974A_POLICY_TIER.md).

---

## Sichtbarkeit vs. Wirkung

| Was Spieler sieht | Was wirklich wirkt |
|-------------------|-------------------|
| XP-Leiste, Tech-Chips | ✅ immer |
| Spezialressourcen-Produktion | ✅ Chain-Techs |
| Politik-Slots / Policies | ✅ inkl. Overdrive (+20 %) |
| Planet-Events | ✅ Event-Pool-Tech |
| Konversions-Queue | ❌ GC-973 |
| Experimental-Risiko | ❌ 972E deferred |
| `policy_tier`-Gate | ✅ unlock-only (GC-974A) |

**UX-Fortschritt (GC-972):** XP transparent, ehrliche Popover, keine falschen Conversion-/Risiko-Versprechen.

---

## Empfohlene Balancing-Reihenfolge (nach GC-974 Review)

| Prio | Ticket-Idee | Inhalt |
|-----|-------------|--------|
| P0 | **GC-974A** | `policy_tier`-Semantik fixen | ✅ Done |
| P1 | **GC-974B** | Deep-Core-Pfad parity (Bonus-Tech oder `mantle_alloy` rate) |
| P1 | **GC-974C** | Trade/Military/Trait-Techs — Sichtbarkeit oder Schwellen |
| P2 | **GC-974D** | Science T3 Event-Rate / T5-Brücke |
| P2 | **GC-974E** | Early-Tech Identity (T1 Industry vs Science vs Ecology) |
| — | **GC-973** | Conversion — eigenes Epic, nicht in 974 mischen |
| — | **post-972E** | Experimental-Risiko |

---

## Abhängigkeiten (Roadmap)

```
GC-972 (Dead Hooks A–D) ✅
    ├── GC-974 (Balancing & Identity) ← jetzt
    ├── GC-973 (Conversion Queue)     ← danach, großes System
    └── GC-972E (Experimental Risk) ← nach Product-OK, nicht eilen
```

**Grundsatz (bestätigt):**

- **GC-972** = vorhandene kaputte Hooks reparieren  
- **GC-973** = neues Gameplay entwickeln  
- **GC-974** = Alpha-Balancing auf solidem Fundament

---

## Nächster Cursor-Prompt (GC-974A Beispiel)

```text
Implementiere GC-974A aus docs/GC-974_PLANET_EVOLUTION_BALANCING.md:
- ~~policy_tier Semantik klären~~ → ✅ GC-974A
- Tests für mandatory_overdrive mit/ohne governance_t1
- Keine Seed-Balance-Zahlen ändern außer nötig für Intent-Fix
```

---

## Referenzen

- [GC-972_PLANET_TECH_DEAD_MECHANICS.md](GC-972_PLANET_TECH_DEAD_MECHANICS.md)
- [GC-973_PLANET_CONVERSION_QUEUE.md](GC-973_PLANET_CONVERSION_QUEUE.md)
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md)
