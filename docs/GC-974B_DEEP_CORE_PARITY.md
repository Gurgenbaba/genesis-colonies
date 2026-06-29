# GC-974B — Deep-Core-Parity (Industry `mining_path`)

> **Epic:** EPIC-05 Planet Evolution  
> **Status:** ✅ Done (Jun 2026)  
> **Stand:** Jun 2026  
> **Owner:** `game/planet_evolution/` (Seed + `economy.py` / `mechanics.py` Consumer)

---

## Warum zuerst 974B (vor 975B / 975C)

`industry_t2_mining_path` ist eine **irreversible** Entscheidung. Spieler bewerten Pfade in den ersten Tagen nach **sofort spürbaren** Belohnungen — nicht nach späterem Potenzial.

| | Orbital (`orbital_mining`) | Deep Core (`deep_core`) |
|---|---------------------------|-------------------------|
| **Gefühl heute** | „Sofort stärker“ | „Irgendwann wird das gut“ |
| **T2-Bonus-Tech** | ✅ `orbital_t2_zero_g_foundry` (+15 % Ferronit, live) | ❌ fehlt |
| **T3-Chain-Rate** | `refined_ferronit` **120/h** | `mantle_alloy` **60/h** |
| **Chain-Risiko** | 2 % Unfall | 3 % Mantelbeben |
| **Endgame** | Overdrive +20 % *(beide Pfade)* | gleich |

**Risiko ohne Fix:** Meta wird „nimm immer Orbital“ — die Pfadwahl wird zur **falschen Antwort**, nicht zur Spielstil-Frage.

**975B (tote Conversion/Experimental-Techs) bewusst später:** Interim-Boni würden mit GC-973 / GC-972E kollidieren. **974B** hat keine solche Abhängigkeit.

---

## Neue Designregel (Pfadentscheidungen)

> **Jede irreversible Pfadentscheidung muss mindestens drei klar erkennbare Vorteile gegenüber dem anderen Pfad besitzen.**

„Vorteil“ = für den Ziel-Spielstil **messbar und in Copy kommunizierbar** (Server-Effekt, nicht nur Flavor).

Nicht: ein Pfad +15 % live, der andere „vielleicht später“.

### Ziel-Identität (gleich stark, unterschiedlich)

| Dimension | Orbital | Deep Core |
|-----------|---------|-----------|
| Förderung | Verarbeitung, Veredelung | Rohertrag, Tiefenförderung |
| Industrie | Stabil, effizient | Riskant, spitzenertragreich |
| Materialien | Spezial-Veredelung (`refined_ferronit`) | Seltene / Mantel-Materialien (`mantle_alloy`, Bulk) |
| Spielstil | Sicher, planbar | Höheres Upside, etwas mehr Risiko |

**Akzeptanz (30-Tage-Test):** Beide Pfade gleich attraktiv für unterschiedliche Spieler — nicht gleiche Boni kopiert.

---

## Ist-Zustand: Tech-Baum pro Pfad

```text
industry_t1_automation (beide)
        │
industry_t2_mining_path  ← IRREVERSIBLE CHOICE
        ├─ orbital_mining ─────────────────┬─ deep_core ───────────────
        │                                  │
orbital_t2_zero_g_foundry (+15% Ferronit) │  (KEIN T2-Äquivalent)
        │                                  │
industry_t3_orbital_refinery              industry_t3_mantle_tap
  chain refined_ferronit 120/h              chain mantle_alloy 60/h
        │                                  │
        └──────── industry_t4_mass_foundry (beide, Conversion tot) ────┘
                        │
              industry_t5_overdrive (beide, Policy live)
```

### Orbital — aktuelle Vorteile (≥3, alle live)

1. **T2 Sofort-Bonus:** +15 % `refined_ferronit` (`chain_output_bonus`)
2. **Höhere Chain-Basisrate:** 120/h vs. 60/h
3. **Niedrigeres Chain-Risiko:** 2 % vs. 3 % `mantle_quake`
4. **Spec-Synergie:** `forge_world` Export T1 `refined_ferronit`

### Deep Core — aktuelle Vorteile

1. **Eigene Ressourcen-Identität:** `mantle_alloy` (situativ wertvoll für Spec/Import)
2. *(Copy verspricht „mehr Rohertrag“ — **nicht numerisch implementiert**)*
3. *(Kein dritter klarer Live-Vorteil)*

→ **Regelverletzung:** Deep Core erfüllt die 3-Vorteile-Regel nicht.

---

## Vorschlag GC-974B (Umsetzungsrichtung)

**Leitplanke:** Keine Orbital-Nerfs. Deep Core **aufholen** durch eigene Identität. Bestehende Hooks bevorzugen (`chain_output_bonus`, Chain-Defs, `risk_json` auf Chains).

### Option A — Deep-Core T2-Tech (empfohlen, symmetrisch zu Orbital)

Neuer Seed-Eintrag (Key-Vorschlag): `deep_core_t2_mantle_excavator`

| Feld | Wert |
|------|------|
| Branch | `INDUSTRY` oder `DEEP_CORE` |
| Tier | 2 |
| Req | `locked_choices.mining_path = deep_core` |
| Mechanics | z. B. `{"chain_output_bonus":{"mantle_alloy":0.15}}` oder `{"chain_output_bonus":{"mantle_alloy":0.18}}` |
| Copy | „Aggressive Mantel-Förderung — höherer Ertrag, etwas instabiler“ |

**Effekt:** Mantel 60/h → 69/h (+15 %), immer noch unter Orbital-138/h auf Ferronit — **aber** Mantel ist seltener/höherwertig in Spec-Ökonomie; ggf. Basisrate Mantel leicht anheben (siehe B).

### Option B — Chain-Basisrate `mantle_alloy` anpassen

Aktuell: 60/h vs. Ferronit 120/h (2:1 ohne klares Design-Dokument).

Vorschlag: `mantle_alloy` auf **75–90/h** oder Output-Kosten reduzieren, damit T3 allein schon spürbar ist, bevor T2-Bonus greift.

→ Migration `087_pe_deep_core_chain_rates.sql` (nur wenn B ohne A oder kombiniert).

### Option C — Sofort-Flag bei Pfadwahl `deep_core`

Bei `make_locked_choice(..., deep_core)` zusätzlich kompilieren:

- `chain_output_bonus` auf `raw_ferronit_bulk` oder
- `metal`/`crystal` Grundproduktion-Mult (neuer Consumer nötig — **nur wenn kein Hook passt**)

Vorteil: Belohnung **ab Tag 1** nach T2-Wahl, ohne extra Tech-Key.  
Nachteil: Neuer Consumer / Pfad-Flag-Compile — etwas mehr Code als Option A.

### Option D — Risiko/Ertrag (Identität „riskanter, stärker“)

- Mantel-Chain: Output +10–15 %, `mantle_quake` chance leicht erhöhen (z. B. 3 % → 4 %)
- Oder Deep-Core-Events aus `forge_rare_metal_vein` / `deep_mining` Spec-Pool stärker gewichten

Passt zur Copy „riskantere Industrie-Ketten“ — braucht klare UI-Warnung.

### Empfohlenes Paket (974B Minimal)

| # | Maßnahme | Aufwand |
|---|----------|---------|
| 1 | **Deep-Core T2-Tech** (Option A) | Seed + Locale + 2–3 Tests |
| 2 | **Mantel-Basisrate** leicht erhöhen (Option B, klein) | Migration |
| 3 | **Choice-Copy** aktualisieren — 3 konkrete Vorteile pro Pfad in UI | Locales (9 Sprachen) |
| 4 | Pfad-Vergleich im Choice-Modal (974B-UX, optional gleiches Ticket) | Template/Dashboard |

**Nicht in 974B:** `industry_t4` Conversion-Fix (→ GC-973), Orbital-Nerfs, neue Policies.

---

## Ziel-Vorteils-Matrix (nach 974B)

| # | Orbital | Deep Core |
|---|---------|-----------|
| 1 | +15 % Veredeltes Ferronit (Zero-G) | +15 % Mantel-Legierung (T2 Deep-Core-Tech) |
| 2 | Stabile Veredelungskette (120/h, 2 % Risiko) | Höherer Spitzenertrag / selteneres Material (75–90/h oder stärkerer Bonus) |
| 3 | Export-Synergie `refined_ferronit` / Forge World T1 | Mantel-Synergie `forge_world` T2 / Deep-Mining-Spec / Bulk-Rohertrag |
| Spielstil | Effizient, planbar | Riskanter, roher, industrie-schwer |

Beide Pfade: T4/T5 shared (Conversion später, Overdrive live).

---

## Technische Constraints (GC-000)

- Kein Frontend-Gameplay-Math — Boni über `mechanics_json` → `compile_planet_mechanics` → `economy.py`
- `chain_output_bonus` dict-Format bereits live (972B)
- Neue Tech: `INSERT` in Migration, nicht nur `017` editieren
- Tests: Deep-Core-Pfad produziert messbar mehr nach T2; Orbital unverändert
- Locales: alle 9 Sprachen

### Dateien (geschätzt, max 5)

1. `migrations/087_pe_deep_core_parity.sql` — T2-Tech + ggf. Chain-Rate
2. `game/planet_evolution/definitions.py` — nur wenn Loader-Anpassung nötig (meist nicht)
3. `tests/test_planet_evolution.py` — Parity-Tests
4. `locales/*.json` — Tech + Choice-Copy
5. `docs/GC-974B_DEEP_CORE_PARITY.md` — Status auf Done nach Merge

---

## Tests (Akzeptanz)

1. `orbital_mining` + Zero-G: `refined_ferronit` weiterhin 138/h (138 baseline unverändert)
2. `deep_core` + neues T2: `mantle_alloy` > 60/h (Zielwert im Test fixieren)
3. Deep-Core-T2 **nicht** queuebar auf Orbital-Pfad
4. Choice-UX zeigt je Pfad ≥3 dokumentierte Vorteile (manuell / optional Snapshot)

---

## Roadmap (Product-Reihenfolge, bestätigt)

```text
1. GC-974B  Deep-Core-Parity          ← JETZT (dieses Ticket)
2. GC-975C  Gelbe Techs stärken       (Handel, Governance, Trait, Breakthrough)
3. GC-975B  Tote Techs                (mit GC-973 / GC-972E — keine Interim-Boni)
```

Siehe auch [GC-975_PLANET_EVOLUTION_REWARD_PASS.md](GC-975_PLANET_EVOLUTION_REWARD_PASS.md).

---

## Ergebnis (GC-974B implementiert)

- **Migration `087`:** `mantle_t2_deep_core_refinery` (+15 % `mantle_alloy`), Basisrate 60 → 90/h
- **Choice-UI:** drei Vorteile pro Pfad (`pe_choice_benefit_*`)
- **Tests:** Seed, Pfad-Gate, Compile, Economy, Orbital unverändert

---

## Explizit out of scope

- Conversion-Queue / `industry_t4` Consumer (GC-973)
- Experimental-Linie (GC-972E)
- Science-Pfad-Parity (separates Ticket falls nötig)
- Planet-Cap ↔ Level (GC-975E)
