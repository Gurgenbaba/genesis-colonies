# GC-975 — Planet Evolution Reward Pass

> **Epic:** EPIC-05 Planet Evolution  
> **Status:** 📋 Analyse & Design-Grundsatz — **keine Implementierung in diesem Ticket**  
> **Stand:** Jun 2026  
> **Voraussetzung:** GC-972A–D ✅, GC-974A ✅, GC-973 / GC-972E geplant

---

## Produkt-These

Planet Evolution ist **kein zweiter Forschungsbaum**, sondern die **Entwicklung des Planeten**.

| Schicht | Rolle |
|---------|--------|
| **Planet-Level** | Langfristiger Imperiums-Reward (Expansion, Freischaltungen, Charakter der Welt) |
| **Planet-Techs** | Werkzeuge — machen den Planeten **sofort** effizienter |
| **Planet-XP** | Brücke zwischen beiden — jede Tech liefert XP **zusätzlich** zum Sofort-Effekt |

**Kernschleife (Soll):**

```text
Planet-Tech
      │
      ▼
Sofort stärker (Produktion, Forschung, Handel, Verteidigung, …)
      │
      ▼
+ Planet-XP
      │
      ▼
Planet-Level steigt
      │
      ▼
Freischaltungen (Spezialisierung, Export, Policies, Expansion-Sites, …)
      │
      ▼
Größeres / stärkeres Imperium
```

---

## Kanonische Designregel (GC-975)

> **Jede Planet-Tech muss mindestens einen sofort spürbaren Gameplay-Effekt besitzen.**
>
> Planet-XP allein reicht **niemals** als Belohnung.

### Ergänzung: Irreversible Pfadentscheidungen (GC-974B)

> **Jede irreversible Pfadentscheidung muss mindestens drei klar erkennbare Vorteile gegenüber dem anderen Pfad besitzen.**

Gilt zuerst für `industry_t2_mining_path` — siehe [GC-974B_DEEP_CORE_PARITY.md](GC-974B_DEEP_CORE_PARITY.md).

### Auslegung

| Kriterium | Zählt als „sofort spürbar“ | Zählt **nicht** |
|-----------|---------------------------|-----------------|
| Numerischer Server-Bonus | +% Produktion, Forschungszeit, Handel, Discovery | — |
| Neue aktive System-Funktion | Chain live, Policy live, Event-Pool live | Flag ohne Consumer |
| Irreversible Pfadwahl | `mining_path` mit klarer Folge-Branch | reine Voraussetzung ohne Effekt |
| Situativ | Trait-gated Chain (wenn Trait da) | nur XP + „folgt später“ |

**Sichtbarkeit:** Ein Effekt kann serverseitig live sein, aber **schwach fühlbar** (z. B. Handelsrouten-Bonus ohne aktive Routen). GC-975 verlangt Runtime-Wirkung; **UX-Sichtbarkeit** ist separates Unterticket (974C).

### Abgrenzung Planet-Level

`LEVEL_UNLOCKS` (L3–L30) und **Homeworld-Level** für Expansion-Sites (`expansion_gates.py`: L5/10/15/20/25) sind der **langfristige** Reward.

**Ist-Lücke (ehrlich):** `get_max_planets_per_player()` ist noch **statisch** (Default 9, Admin-Setting). Kommentar in `game/logic.py` verweist auf künftige Anbindung an Planet Evolution — **noch nicht implementiert**. Die Kolonie-Slot-Schleife ist deshalb heute **teilweise** nur über Expansion-Sites spürbar, nicht über hartes Planet-Cap.

---

## XP-Referenz (immer Langzeit-Bonus)

Formel: `25 + tier × 15` (`compute_planet_research_reward_xp`)

| Tier | XP pro Abschluss |
|------|------------------|
| T1 | 40 |
| T2 | 55 |
| T3 | 70 |
| T4 | 85 |
| T5 | 100 |

XP ist **immer** dabei — aber **nie allein**.

---

## Ist-Analyse: alle 18 Planet-Techs

Legende: **✅** erfüllt Regel · **🟡** schwach/situativ · **❌** verletzt Regel (toter Hook oder nur XP)

| # | Tech (DE) | Key | Tier | XP | Sofort-Effekt heute | Live? | GC-975 |
|---|-----------|-----|-----:|---:|---------------------|-------|--------|
| 1 | Industrie-Automatisierung | `industry_t1_automation` | 1 | 40 | `unlock_queue.conversion:1` | ❌ GC-973 | ❌ |
| 2 | Bergbau-Pfad | `industry_t2_mining_path` | 2 | 55 | Pfadwahl Orbital / Tiefkern | ✅ Gate | 🟡 |
| 3 | Orbitalraffinerie | `industry_t3_orbital_refinery` | 3 | 70 | Chain `refined_ferronit` (~120/h) | ✅ | ✅ |
| 4 | Mantel-Tap | `industry_t3_mantle_tap` | 3 | 70 | Chain `mantle_alloy` (~90/h) + T2 +15 % | ✅ | ✅ |
| 5 | Massengießerei | `industry_t4_mass_foundry` | 4 | 85 | `conversion_batch_bonus:1` | ❌ GC-973 | ❌ |
| 6 | Industrie-Overdrive | `industry_t5_overdrive` | 5 | 100 | Policy `mandatory_overtime` (+20 % Ketten) | ✅ | ✅ |
| 7 | Feld-Labore | `science_t1_field_labs` | 1 | 40 | +10 % Planet-Tech-Forschungszeit | ✅ | ✅ |
| 8 | Quanten-Kartographie | `science_t2_quantum_mapping` | 2 | 55 | Chain `quantum_data` (~40/h) | ✅ | ✅ |
| 9 | Breakthrough-Lab | `science_t3_breakthrough_lab` | 3 | 70 | Event-Pool `science_breakthrough` | ✅ RNG | 🟡 |
| 10 | Experimentelles Tor | `science_t5_experimental_gate` | 5 | 100 | `enable_experimental` + risk_json | ❌ GC-972E | ❌ |
| 11 | Plasma-Harness | `energy_t2_plasma_harness` | 2 | 55 | Chain `dark_plasma` | ✅ Trait | 🟡 |
| 12 | Biomasse-Extraktion | `ecology_t1_biomass` | 1 | 40 | Chain `living_crystal` | ✅ | ✅ |
| 13 | Markt-Protokolle | `trade_t2_market_protocols` | 2 | 55 | +10 % Handelsrouten-Erlös | ✅ | 🟡 |
| 14 | Zivilverwaltung | `governance_t1_civil_admin` | 1 | 40 | `unlock_policy_tier:1` (Tier-1-Policies) | ✅ schwach | 🟡 |
| 15 | Ruinen-Vermessung | `ancient_t1_ruins_survey` | 1 | 40 | Chain `ancient_alloy` | ✅ Trait | 🟡 |
| 16 | Dunkle Materie | `experimental_t1_dark_matter` | 1 | 40 | `enable_experimental` + risk | ❌ GC-972E | ❌ |
| 17 | Befestigung | `military_t2_fortification` | 2 | 55 | Chain `phase_crystal` | ✅ | ✅ |
| 18 | Zero-G-Gießerei | `orbital_t2_zero_g_foundry` | 2 | 55 | +15 % `refined_ferronit` | ✅ | ✅ |
| 19 | Tiefkern-Raffinerie | `mantle_t2_deep_core_refinery` | 2 | 55 | +15 % `mantle_alloy` | ✅ | ✅ |

### Bilanz

| Status | Anzahl | Techs |
|--------|-------:|-------|
| ✅ klar compliant | **9** | T3 Orbital/Mantel, T5 Overdrive, Science T1/T2, Ecology T1, Military T2, Orbital T2 |
| 🟡 schwach / situativ | **6** | Mining path, Breakthrough, Plasma, Trade, Governance, Ruinen |
| ❌ Regelverletzung | **4** | Industry T1/T4, Science T5, Experimental T1 |

**Fazit:** ~56 % der Techs erfüllen die Regel klar. **4 Techs** verletzen sie wegen fehlender Consumer (973/972E). **6 Techs** brauchen Stärkung oder bessere Sichtbarkeit — nicht zwingend neue Mechaniken, teils Copy/UX.

---

## Soll-Matrix (Reward Pass — Vorschlag)

Ziel: Jede Zeile = **mindestens ein Sofort-Bonus** + XP. Keine neuen Tech-Keys in 975 — nur Seed-`mechanics_json` / Consumer-Nachzug wo nötig.

| Tech (DE) | Sofortiger Bonus (Vorschlag) | Langfristig | Abhängigkeit |
|-----------|------------------------------|-------------|--------------|
| Feld-Labore | +10 % Planet-Tech-Speed *(live)* + **+5 % Discovery-Chance** | +40 XP | `discovery_roll_bonus` Consumer ✅ |
| Bergbau-Pfad | Pfadwahl + **+8 % Spezialressource des Pfads** | +55 XP | neuer Flag oder Chain-Mult |
| Orbitalraffinerie | Chain `refined_ferronit` *(live)* | +70 XP | — |
| Mantel-Tap | Chain `mantle_alloy` + **+12 % Mantel-Output** | +70 XP | 974B Parity |
| Massengießerei | `conversion_batch_bonus` *(wenn 973)* oder **+10 % alle Ketten** interim | +85 XP | GC-973A |
| Industrie-Overdrive | Policy +20 % Ketten *(live)* | +100 XP | — |
| Industrie-Automatisierung | Conversion-Slot *(973)* oder **+5 % Metal/Crystal-Tick** interim | +40 XP | GC-973A |
| Quanten-Kartographie | Chain `quantum_data` *(live)* | +55 XP | — |
| Breakthrough-Lab | Event-Pool *(live)* + **+5 % Discovery/Event** | +70 XP | Event-Rate-Flag |
| Experimentelles Tor | Experimental-Slot/Risiko *(972E)* oder **+10 % Science-Chains** interim | +100 XP | GC-972E |
| Plasma-Harness | Chain `dark_plasma` *(live)* | +55 XP | — |
| Biomasse-Extraktion | Chain `living_crystal` *(live)* | +40 XP | — |
| Markt-Protokolle | +10 % Routen *(live)* + Dashboard-Badge | +55 XP | 974C UX |
| Zivilverwaltung | Tier-1-Policies *(live)* + **+5 % Stabilitäts-Drift** oder Policy-Slot-Hinweis L5 | +40 XP | Design-OK |
| Ruinen-Vermessung | Chain `ancient_alloy` + **+5 % Discovery** | +40 XP | — |
| Dunkle Materie | Experimental *(972E)* oder **+5 % Event-Rate** interim | +40 XP | GC-972E |
| Befestigung | Chain `phase_crystal` + **+10 % lokale Verteidigung** | +55 XP | `defense_mechanic` / neuer Mult |
| Zero-G-Gießerei | +15 % Ferronit *(live)* + optional **+5 % alle Ketten** | +55 XP | bereits stark |

**Hinweis zu Beispielen im Product-Brief:** XP-Werte sind tierabhängig (T1 = 40, T3 = 70, nicht pauschal 70).

---

## Bekannte Mechanik-Hooks (für Reward Pass)

Bereits kompilierbar / teils konsumiert — bevorzugt **wiederverwenden** (GC-000 Regel 16):

| Hook | Consumer | Eignung Sofort-Bonus |
|------|----------|---------------------|
| `planet_research_speed_flag` | `planet_research.py` | ✅ live |
| `chain_output_bonus` | `economy.py` | ✅ live |
| `trade_route_bonus` | `economy.py` | ✅ live |
| `discovery_roll_bonus` | `discoveries.py` | ✅ live |
| `unlock_chain` | `economy.py` | ✅ live |
| `enable_policy` / `policy_tier` | `policies.py` | ✅ live |
| `enable_event_pool` | `events.py` | ✅ live |
| `unlock_queue.conversion` | — | ❌ GC-973 |
| `conversion_batch_bonus` | — | ❌ GC-973 |
| `enable_experimental` | — | ❌ GC-972E |

Neue Hooks nur wenn kein bestehender passt — Owner `mechanics.py` + Consumer in §17-Modul dokumentieren.

---

## Pfad-Parität (Industry)

Orbital-Zweig hat **mehr Sofort-Rewards** pro Tech als Tiefkern:

| | Orbital | Tiefkern |
|---|---------|----------|
| T2 | — (nur Pfad) | — |
| T2 Bonus-Tech | `orbital_t2_zero_g_foundry` (+15 %) | **fehlt** |
| T3 | Raffinerie | Mantel-Tap |

→ **GC-974B** (Deep-Core-Parity) ist Vorläufer von GC-975, nicht optional.

---

## Empfohlene Umsetzungs-Reihenfolge

**Product-Reihenfolge (Jun 2026, bestätigt):**

```text
1. GC-974B  Deep-Core-Parity     ← NÄCHSTES Implementierungs-Ticket
2. GC-975C  🟡-Techs (Handel, Governance, Trait, Breakthrough, Discovery-UX)
3. GC-975B  ❌-Techs nur mit GC-973 / GC-972E — KEINE Interim-Boni
4. GC-975E  Planet-Cap ↔ Homeworld-Level (optional, separates Produkt-Ticket)
```

```
GC-975 (Epic, kein Big-Bang)
│
├── 975A — Designregel in PLANET_EVOLUTION.md + Lint-Checkliste für neue Techs
├── 974B — Deep-Core-Parity ✅
├── 975C — Stärke 🟡-Techs (Mining path Choice-UX, Governance, Breakthrough, Trade)
├── 975B — Fix ❌-Techs via GC-973 / GC-972E (kein Interim-Flicken)
└── 975E — Planet-Cap ↔ Homeworld-Level (Produkt — separates Ticket)
```

**Leitplanke:** Kein Reward-Pass-Batch ohne grüne Tests pro Tech-Änderung. Seed-Änderungen in `migrations/NNN_*.sql`, nicht nur `017` editieren.

---

## Explizit out of scope (GC-975 Analyse)

- Neue Tech-Keys / neue Branches
- XP-Formel-Änderung
- Account-Forschung
- Vollständige UI-Redesign Planet-Evolution
- Balance-Tuning aller Zahlen in einem Commit

---

## Akzeptanzkriterien (wenn implementiert)

1. Keine der 18 Techs hat **nur** XP als Effekt (nach 973/972E-Resolution oder ehrlichem Interim-Bonus).
2. Jede Tech hat dokumentierten **Sofort-** und **Langzeit-**Reward in Seed + Player-Copy.
3. Regression-Tests: Mechanik-Flag → messbarer Consumer (Pattern aus GC-972).
4. Hero/Dashboard zeigt mindestens einen Effekt pro abgeschlossener Tech (975C).

---

## Referenz

- [GC-974_PLANET_EVOLUTION_BALANCING.md](GC-974_PLANET_EVOLUTION_BALANCING.md) — Ist-Matrix & Prio
- [GC-974A_POLICY_TIER.md](GC-974A_POLICY_TIER.md) — Policy-Semantik ✅
- [GC-973_PLANET_CONVERSION_QUEUE.md](GC-973_PLANET_CONVERSION_QUEUE.md) — Conversion-Consumer
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — System-Overview
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000, keine Duplicate Math
