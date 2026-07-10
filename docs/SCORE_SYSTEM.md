# Score System — Kanonischer Ressourcenwert

> **Regel:** Punkte sind nichts anderes als der **normierte Gesamt-Ressourcenwert** eines Accounts.  
> Jede Spielmechanik wird darauf zurückgeführt — keine parallelen Punktformeln pro Domäne.

Owner: `game/resource_score.py` · Aggregation: `game/ranking.py` · Persistenz: `player_scores`

---

## Kanonische Umrechnung (3:2:1)

Identisch zum Produktions-Verhältnis (`STANDARD_PRODUCTION_PER_HOUR` in `production_formula.py`):

| Ressource | Punkte pro Einheit |
|-----------|-------------------:|
| Ferronit (`metal`) | 1 / 1 500 |
| Crytite (`crystal`) | 1 / 1 000 |
| Brennzellen (`fuel_cells`) | 1 / 500 |

```text
score_points(metal, crystal, fuel_cells)
  = floor(metal / 1500) + floor(crystal / 1000) + floor(fuel_cells / 500)
```

**Tausch-Neutralität:** Wenn der Trader exakt dieses Verhältnis als Basiswert nutzt, erzeugt reines Umtauschen weder Punkte noch Verluste — Vermögen verschiebt sich nur zwischen den drei Ressourcen.

Score-Äquivalente (für Trader-Validierung):

| Von → Nach | Kurs (score-neutral) |
|------------|----------------------|
| 1 Crytite | 1,5 Ferronit |
| 1 Brennzelle | 3 Ferronit |
| 1 Brennzelle | 2 Crytite |

---

## Erhaltungssatz (Conservation)

```text
Account Score
  = Ressourcen im Lager (alle Planeten)
  + Gebäude (kumulierte Baukosten, alle Level)
  + Forschung (kumulierte Forschungskosten, alle Level)
  + Schiffe (Anzahl × Baukosten)
  + Defense (Anzahl × Baukosten)
  + Planet Evolution (kumulierte investierte Kosten — keine Sonderformel)
  + sonstige Systeme (jeweils über investierte Ressourcen)
```

**Ausgeben von Ressourcen** verschiebt Punkte von `score_resources` nach `score_buildings` / `score_fleet` / … — die **Gesamtpunktzahl bleibt identisch**, solange keine Ressourcen verbrannt oder geschenkt werden.

**Verlust durch Kampf:** Zerstörte eigene Einheiten reduzieren den Account-Score (Vermögen ist weg). **Zerstörungspunkte** (Lifetime Combat Prestige) sind ein **separates** Ranking-Signal — nicht in `score_total` mischen, sonst entsteht ein Logikbruch (verlorene Flotte, aber Punkte bleiben als „Vermögen“ erhalten).

**Ranking-Tabs (Ziel):**

| Tab | Inhalt |
|-----|--------|
| Gesamtpunkte | Aktuelles Vermögen (Erhaltungssatz) |
| Economy | Gebäude + Lager |
| Forschung | Account-Tech investiert |
| Militärbestand | Fleet + Defense (aktiv) |
| Zerstörung | Combat Prestige (lifetime, getrennt) |

---

## Komponenten (Ziel-Schema)

| Spalte | Berechnung |
|--------|------------|
| `score_resources` | Summe aller Planet-Lager ÷ Kanon |
| `score_buildings` | Σ kumulative Upgrade-Kosten (metal+crystal+fuel) ÷ Kanon |
| `score_research` | Σ kumulative Tech-Kosten (alle drei Ressourcen) ÷ Kanon |
| `score_fleet` | Σ (Anzahl × Schiff-Baukosten) ÷ Kanon |
| `score_defense` | Σ (Anzahl × Defense-Baukosten) ÷ Kanon |
| `score_planet_evolution` | Σ investierte Evo-Kosten ÷ Kanon (kein level×100-Sonderweg) |
| `score_total` | Summe aller Komponenten |
| `score_combat` | `score_fleet + score_defense` (abgeleitet, nicht in total doppelt) |
| `score_destroyed` | Lifetime Combat Prestige — **nicht** in `score_total` |

**Verboten nach Migration:**

- `score_cost_exponent` (Potenz auf Summen)
- `score_weight_*` pro Kategorie (unterschiedliche Gewichtung)
- `metal + crystal` ohne Brennzellen
- Hardcodierte `score_value` in `fleet_defs` / `defense_defs`, die von `build_cost` abweichen
- Planet-Evolution-Punkte aus `level×100 + tier×500` ohne Ressourcenbezug

---

## Beispiele

### Gebäude

Kosten Stufe gesamt: 450 000 Ferronit, 300 000 Crytite, 50 000 Brennzellen

```text
450 000/1500 + 300 000/1000 + 50 000/500 = 300 + 300 + 100 = 700 Punkte
```

### Forschung (kumulativ)

| Level | Kosten (F/C/B) |
|-------|----------------|
| L1 | 1 000 / 500 / 0 |
| L2 | 2 000 / 1 000 / 0 |
| L3 | 4 000 / 2 000 / 500 |

Gesamt: 7 000 / 3 500 / 500 → `4 + 3 + 1 = 8` Punkte (floor pro Ressource).

### Schiffe

60 000 / 40 000 / 10 000 pro Schiff → `40 + 40 + 20 = 100` Punkte.  
100 Schiffe → 10 000 Punkte. Keine Extraformel.

---

## Ist-Zustand (Abweichungen — Stand vor GC-SCORE-REBASE)

| Problem | Aktueller Code |
|---------|----------------|
| Keine Lager-Ressourcen im Score | `compute_player_scores()` zählt nur Assets |
| Brennzellen ignoriert | Fleet/Defense/Research/Buildings: oft nur `metal + crystal` |
| Unterschiedliche Gewichte | `score_weight_research` default **0.01**, eigene Weights pro Kategorie |
| Exponent-Verzerrung | `score_cost_exponent` auf Summen |
| Hardcodierte `score_value` | `fleet_defs.py`, `defense_defs.py`, `combat_models._score_from_build_cost` |
| Evo-Sonderformel | ~~`planet_evolution/scoring.py`~~ entfernt (GC-SCORE-E) |
| Trader ≠ Score-Basis | ~~Exchange 2:1 / Fuel 20:14~~ → score-neutral defaults (GC-SCORE-F) |
| OGameX-Exploit-Risiko | Unterschiedliche Bewertung pro Ressource/Typ |

---

## Implementierung (Epic — Phasen)

| Ticket | Scope |
|--------|--------|
| **GC-SCORE-A** | ✅ `game/resource_score.py`: `score_from_resources()`, `score_from_cost_dict()` — Single Source of Truth |
| **GC-SCORE-B** | ✅ `compute_player_scores()` via `resource_score`; `score_resources`; exponent/weights entfernt |
| **GC-SCORE-C** | ✅ Fleet/Defense: `score_value` aus `build_cost` via `resource_score`; hardcodierte Werte entfernt |
| **GC-SCORE-D** | ✅ `cumulative_upgrade_resource_totals` / `cumulative_research_resource_totals` — Ranking nutzt Owner |
| **GC-SCORE-E** | ✅ Planet Evolution: `cumulative_planet_research_resource_totals` + `ascension_invested_resource_totals` → `resource_score` |
| **GC-SCORE-F** | ✅ Trader: score-neutrale Defaults (1.5 / 3 / 2), Validierung + `exchange_score_exploit`-Guard |
| **GC-SCORE-G** | ✅ Tests + Admin-Recompute + Live-Audit (`ranking_score_rebase`: persistiert vs. `compute_player_scores`) |

Nach Deploy: **einmalig** `POST /api/admin/ranking/recompute` — erwartete Score-Verschiebung dokumentieren (kein Bug).

---

## Verwandte Docs

- [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md) — 3:2:1 Produktionsanker
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Trader Hub
- [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md) — Forschungskosten
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) — Defense Score
- [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) — Military / Destruction
- [GC-822_LIVE_ECONOMY_QA.md](GC-822_LIVE_ECONOMY_QA.md) — Ranking-Drift-Audit
