# Research System

Account-weite Technologie-Forschung.  
**Stand:** Research-Network-Ascension · Ankerkurven: [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

**Abgrenzung:** Planet-spezifische Forschung (Evolution) lebt in `game/planet_evolution/planet_research.py` — nicht dieses Dokument.

---

## Tech-Keys

`RESEARCH_TECHS` in `game/research.py`:

| Key | Kategorie | Lab (min) |
|-----|-----------|-----------|
| `energy_tech` | energy | 1 |
| `mining_tech` | metal | 1 |
| `buildtime_tech` | construction | 2 |
| `storage_tech` | storage | 1 |
| `drone_tech` | drones | 2 |
| `navigation_tech` | navigation | 3 (+ drone_tech 2) |
| `engine_tech` | engine | 3 (+ energy_tech 2) |
| `weapon_tech` | weapon | 2 |
| `armor_tech` | armor | 2 (+ weapon_tech 1) |
| `shield_tech` | shield | 3 (+ armor_tech 1) |
| `fuel_efficiency` | propulsion | 2 (+ energy_tech 1) |

Jede Tech: `base_cost_m/c`, `base_time`, `cost_factor` (Tier-Referenz), verschachtelte Tech-Requirements.

---

## Scope

| Aspekt | Scope |
|--------|-------|
| Levels | `research_levels.user_id` — **Account** |
| Queue | `research_queue.user_id` — **Account** |
| Lab-Level für Tech-Unlocks | **Empire-wide max** `research_lab` über alle Kolonien |
| Forschungsnetzwerk-Kapazität | **Stärkstes einzelnes Forschungslabor** inkl. dessen Ascension-Rang; Ränge mehrerer Welten werden nicht addiert |
| Ressourcen-Zahlung | **Context planet** metal/crystal |
| Research-Lab-Ascension | **Planet-spezifischer** Prestige-State in `research_lab_ascension`; accountweit wirkt nur das stärkste Labor |

---

## Forschungs-Queue / Forschungsnetzwerk

Kanonischer Owner für die Queue-Kapazität: `game.research_lab_ascension.research_queue_capacity()`.

| Fortschritt | Prestige-Kapazität |
|-------------|-------------------:|
| Start / Labor 0–29 | **2 Slots** |
| Forschungslabor 30–39 | **3 Slots** |
| Forschungslabor 40–49 | **4 Slots** |
| Forschungslabor 50+ ohne Ascension | **5 Slots** |
| Ascension I | **6 Slots** |
| Ascension II | **7 Slots** |
| Ascension III | **8 Slots** |
| Ascension IV | **9 Slots** |
| Ascension V | **10 Slots** |

Regeln:

- Basisformel: `min(5, max(2, floor(lab_level / 10)))`, mit 2 Starter-Slots.
- Prestige-Cap: **10 Slots** = 5 Basis + maximal 5 Ascension-Slots.
- `game_settings.research_queue_limit` bleibt als bestehender **Override-Floor** kompatibel.
- Galactic-Directive-Slots bleiben bestehende **additive externe Boni** und werden nicht durch den Prestige-10er-Cap abgeschnitten.
- **Slots sind Planungsplätze, keine parallelen Forschungsprozesse.** Die Queue bleibt strikt sequenziell.
- Nach Cancel/Enqueue terminiert `recalculate_research_queue_finish_times()` die Folgejobs weiterhin hintereinander neu.
- Finish: `queue_engine.finish_player_research_jobs`.
- Cancel: **GC-831 Refund** (100 % pending / 50 % active); Restqueue wird neu terminiert.

Migration `008`: `research_queue.start_at` für präzise UI-Fortschritte.  
Kosten-Snapshot auf Row: Migration `076`.  
Research-Lab-Ascension-State: Migration `176`.

---

## Forschungsnetzwerk-Ascension

Owner: `game/research_lab_ascension`.

| Rang | Gate | Labor-Cap danach | Queue | zusätzlicher Research-Speed | Tribute-Gewichtung |
|------|-----:|-----------------:|------:|-----------------------------:|-------------------:|
| 0 | — | 50 | bis 5 | — | — |
| I | L50 | 60 | 6 | +2 % | 40 % Ferronit / 60 % Crytite |
| II | L60 | 70 | 7 | +4 % | 35 / 65 |
| III | L70 | 80 | 8 | +6 % | 30 / 70 |
| IV | L80 | 90 | 9 | +8 % | 25 / 75 |
| V | L90 | 100 | 10 | +10 % | 20 / 80 |

Wichtige Invarianten:

- Eine Welt muss das jeweilige Gate **fertig gebaut** haben; gequeue-te Laborlevel zählen nicht.
- Eine offene `research_lab`-Bauqueue blockiert Ascension auf dieser Welt.
- Tribute wird serverseitig aus der bestehenden Endgame-/Ascension-Kostenkurve abgeleitet: 25 % des kanonischen Upgrade-Spends der 40 Level bis zum jeweiligen Gate; nur die Ferronit/Crytite-Gewichtung wird research-spezifisch verschoben.
- Ressourcen werden exakt und transaktional vom Kontextplaneten abgezogen.
- PostgreSQL nutzt Player-/Planet-Locks plus konditionales Rank-Update gegen Doppel-Ascension/Races.
- Mehrere ascended Labore werden **nicht summiert**. Der Resolver wählt genau das Labor mit der höchsten wirksamen Prestige-Kapazität; Ties werden deterministisch aufgelöst.
- Rank V ist Endpunkt dieses Prestige-Pfads; die allgemeine Research-Queue bleibt dennoch sequenziell.
- Ascension wird wie andere Gebäude-Ascensions **am Forschungslabor in der Gebäude-UI** aktiviert; `/research` zeigt das Forschungsnetzwerk nur read-only an.

---

## Zeitberechnung

`EffectResolver.get_research_time_seconds()` (GC-825 + Research-Network-Ascension):

- **Basis:** Log-Anker in `economy_balance.research_time_anchor_hours()` (L10 = 1,5 h … L120 = 4320 h)
- **Tech-Tier:** `base_time / 840` (energy_tech = 1,0)
- ÷ Settings: `build_speed` (Default **1.1**), `research_speed` (Default **0.85**)
- ÷ `research_lab_bonus` (+10 %/Level über 1)
- ÷ `research_time_speed` (buildtime_tech, academy +5 %/Level)
- ÷ Research-Lab-Ascension-Speed: **+2 % pro Rang**, maximal **+10 %** bei Rank V

Der Ascension-Speedbonus wird vom selben stärksten Forschungsnetzwerk abgeleitet wie die Prestige-Kapazität; Ascension-Ränge mehrerer Planeten stapeln nicht.

**Kosten:** `economy_balance.research_upgrade_cost()` — `reference_production(metal+crystal @ level) × research_cost_afford_hours(level)` (GC-RESEARCH-COST-REBALANCE) × Tech-Tier aus `base_cost_m/c`.

Afford-Anker (`RESEARCH_COST_AFFORD_HOURS`, energy_tech Tier 1.0):

| Level | Ziel-Afford (h Produktion) |
|-------|----------------------------|
| 1→10 | 3 h → 8 h (linear) |
| 20 | 24 h |
| 30 | 96 h (~4 Tage) |
| 40 | 336 h (~2 Wochen) |
| 50 | 720 h (~30 Tage) |
| 60 | 1080 h |
| 80 | 2160 h |
| 100 | 4320 h |
| 120 | 8640 h |

Beispiel energy_tech L19: ~940k Gesamt · storage_tech L19 (Tier 0,67): ~625k Gesamt.

Legacy-Exponential (`base_time × cost_factor^(level-1)`) nur noch als Audit-Helfer in `economy_balance`.

---

## EffectResolver-Integration

**Aktiv (Economy / Time / Combat / Fleet):**

| Tech | Effekt |
|------|--------|
| `energy_tech` | `mine_energy_factor` |
| `mining_tech`, `crystal_tech`, `drone_tech` | Prod-Faktoren (metal / crystal / both) |
| `storage_tech` | `storage_factor` (+15 %/Lvl, additiv) |
| `buildtime_tech` | Build + research speed |
| `weapon_tech`, `armor_tech`, `shield_tech` | Combat modifiers → `simulate_battle()` |
| `navigation_tech`, `engine_tech` | `fleet_speed_multiplier` → `fleet.py` / `fleet_calc.py` |
| `fuel_efficiency` | `fuel_efficiency_factor` → `fleet_calc.calculate_fuel_cost()` |
| Research-Lab-Ascension | Research-Zeitmultiplikator +2 % pro Rang, max +10 % |

Radar `scan_range` (via `radar_array`) is consumed by the Deep-Space Threat Net — see [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) / [EFFECTS.md](EFFECTS.md).

Details: [EFFECTS.md](EFFECTS.md), [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md), [FLEET_SYSTEM.md](FLEET_SYSTEM.md).

Research-Effekte skalieren linear pro Level ohne Balancing-Cap. Anzeige-% ist unbegrenzt; Gameplay clampet nur physisch (Verbrauch ≥ 0, Zeiten ≥ 1s).

---

## APIs

| Route | Methode | Body |
|-------|---------|------|
| `/research` | GET | SSR |
| `/research_start/<tech_key>` | GET | Legacy |
| `/api/research/start` | POST | `{ tech_key, request_id? }` |
| `/api/research/cancel` | POST | `{ job_id }` |
| `/api/research/ascend-lab` | POST | Research-Lab-Ascension der aktiven/context world |

Tech-Tree Visualisierung: `/techtree` (`game/techtree.py`).

---

## UI

- Template: `templates/research.html`
- **Forschungsnetzwerk-Header auf `/research`:** read-only; belegte/gesamte Slots, stärkstes Labor, Ascension-Rang und nächster Unlock.
- **Gebäude-UI:** Forschungslabor zeigt Rank, Queue-Kapazität, Gate-Fortschritt und Research-Speedbonus; bei erreichtem Gate läuft die Ascension dort über Tribute-CTA + Bestätigungsdialog.
- **Queue-UX (GC-536C):** Status in jeder Tech-Card (`queue_job` via `game/queue_card.py`).
- Kompakt-Header: `#research-queue-compact`.
- Poll/Action-State: Research-State verwendet dieselbe serverseitig aufgelöste Kapazität; keine duplizierte Client-Mathematik.
- Card-Queue: `GC.renderCardQueueBlock` (domain `research`).

---

## Ship / Building Requirements

- Schiffe: `game/ship_requirements.py` + `fleet_defs`
- Gebäude: `BUILDING_REQUIREMENTS` in buildings.py
- Forschungslabor-Levelcaps 50→100 werden durch `game.research_lab_ascension.max_lab_level_for_rank()` bestimmt.

---

## Tests

```bash
python -m pytest \
  tests/test_research_lab_ascension.py \
  tests/test_research_requirements.py \
  tests/test_gc825_research_time_rebalance.py \
  tests/test_gc830_max_queue_buttons.py \
  tests/test_queue_static_contract.py -v
```

Die normale PR-CI bleibt Release-Gate, insbesondere PostgreSQL Numeric/Navigation sowie Genesis Browser Sentinel.

---

## Player Article

```yaml
---
codex_id: research
band: I
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
routes:
  - research_view
related_codex:
  - buildings
  - fleet
  - planet_evolution
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

Account-Forschung verbessert dein **gesamtes Imperium** — Energieeffizienz, Produktion, Flottengeschwindigkeit und Kampfwerte. Kosten zahlst du von der **aktiven Welt**. Das Forschungsnetzwerk beginnt mit 2 Planungsplätzen, wächst bei Labor 30/40/50 auf 3/4/5 und über Ascension I–V bis auf 10 Slots; die Forschung selbst bleibt sequenziell.

## Summary

**Account-Forschung** ist **spielerweit**: ein Tech-Tree mit sequenzieller Queue, Zahlung in Ferronit/Crytite vom Kontext-Planeten und einem Forschungsnetzwerk, dessen Kapazität vom stärksten einzelnen Labor bestimmt wird. Ab Labor 50 führt die Research-Lab-Ascension über fünf Prestige-Ränge bis 10 Queue-Slots und +10 % Research-Speed. Sie ist **nicht** Planet Evolution / Planet-Tech — das ist pro Welt ein separates System.

## Why

Forschung löst Engpässe imperiumsweit: mehr Lager, schnellere Bauzeiten, effizientere Minen, mehr Flottenslots, stärkere Waffen. Die Forschungsnetzwerk-Ascension macht extrem hohe Laborlevel im Endgame sinnvoll, ohne durch echte Parallelforschung die Research-Economy zu vervielfachen.

## How it works

- **Forschungslabor** (mind. Stufe 1 empire-wide max) schaltet Techs frei.
- Queue-Kapazität: 2 Slots früh, 3 bei L30, 4 bei L40, 5 bei L50.
- Ab L50 kann das Labor ascenden; jeder Rank erweitert den nächsten Labor-Cap um 10 Level und gibt dauerhaft +1 Prestige-Slot sowie +2 % Research-Speed.
- Ascension I–V führt dadurch bis L100 / 10 Prestige-Slots / +10 % Speed.
- Nur das stärkste einzelne Labor bestimmt die Forschungsnetzwerk-Kapazität; Ränge verschiedener Welten werden nicht addiert.
- Die Queue bleibt sequenziell: zusätzliche Slots erlauben längere Forschungsketten im Voraus, nicht mehrere gleichzeitig laufende Forschungen.
- Techs haben **Voraussetzungen** — Kette planen (Energie vor Antrieb, Extraktion vor Navigation).
- **Interstellar Expansion** (Account-Tech) gehört zur Expansion — Gates für neue Welten (siehe Expansion Protocol).
- Planet-Tech auf `/planet-evolution` ist **Welt-Forschung**, nicht dieses System.

## Related Systems

- buildings
- fleet
- combat
- defense
- expansion
- planet_evolution

---

## Ranking / Forschungspunkte

Owner: `game/ranking.py` → `compute_player_scores()`.

| Regel | Detail |
|-------|--------|
| Basis | Pro Tech: **kumulative** investierte Kosten (Ferronit + Crytite) für Level 1 … aktuelles Level |
| Formel pro Tech | `_sum_costs_up_to_level(base_m, base_c, cost_factor, level)` — identisch zur Gebäude-Logik |
| Keine Doppelwertung | Nur `research_levels.level`; Queue-Ziellevel und Speed-Boni fließen **nicht** in Punkte ein |
| Skalierung | `score_cost_exponent` (game_settings, default 1.0) auf die Summe aller Techs |
| Gewicht | `score_weight_research` (game_settings, empfohlener Default **0.01**) |
| Formel | **Research Score** = kumulative Forschungskosten (Ferronit + Crytite) × `score_weight_research` |
| Live-Tuning | Admin Panel → Balance; überschreibt nur den gespeicherten Wert, kein Auto-Migrate auf Live-DBs |
| Recompute | Admin → Ranking neu berechnen (`/api/admin/ranking/recompute`) oder `recompute_and_upsert_score()` |

Ascension-Queueplätze und Ascension-Speedbonus erzeugen selbst keine zusätzlichen Research-Punkte; Forschungspunkte folgen weiterhin den abgeschlossenen Tech-Leveln.

---

## Commander Tips

- Forschung sollte selten stillstehen — die erweiterten Queue-Slots sind für langfristige Vorausplanung gedacht.
- Labor auf mindestens einer Welt gezielt hoch halten; für das Forschungsnetzwerk zählt das stärkste einzelne Labor.
- Ab L50 Tribute/Gate bis zur nächsten Ascension mitplanen.
- Tech-Tree-Seite zeigt Abhängigkeiten; priorisiere Engpass-Techs vor Output-Push.

## FAQ

**Warum kann ich eine Tech nicht starten?**  
Fehlendes Labor-Level, fehlende Vor-Tech, volle Forschungsqueue oder nicht genug Ferronit/Crytite auf der aktiven Welt.

**Laufen bei 10 Slots zehn Forschungen gleichzeitig?**  
Nein. Es laufen weiterhin sequenziell geplante Jobs. 10 Slots bedeuten bis zu 10 vorausgeplante Forschungsaufträge.

**Kann ich mehrere Labore ascenden und die Slots addieren?**  
Nein. Das stärkste einzelne Labor bestimmt die Forschungsnetzwerk-Kapazität.

**Unterschied Planet-Tech vs. Account-Forschung?**  
Account = Imperium. Planet-Tech = nur die gewählte Welt in Planet Evolution.

## Discord Summary

**Account-Forschung — Forschungsnetzwerk-Ascension**

Queue bleibt sequenziell, wächst aber mit dem stärksten Forschungslabor: 2 Slots → L30: 3 → L40: 4 → L50: 5. Danach Ascension I–V bis 10 Slots, L100 und +10 % Research-Speed. Keine Slot-Summe über mehrere Planeten.