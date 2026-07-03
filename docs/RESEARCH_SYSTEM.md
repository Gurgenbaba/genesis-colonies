# Research System

Account-weite Technologie-Forschung.  
**Stand:** v1.5.9.x · Ankerkurven: [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

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
| Lab-Level für Unlocks | **Empire-wide max** `research_lab` über alle Kolonien |
| Ressourcen-Zahlung | **Context planet** metal/crystal |

---

## Forschungs-Queue

| Eigenschaft | Wert |
|-------------|------|
| Default limit | **2** (`RESEARCH_QUEUE_LIMIT`) |
| Bonus limit | **3** wenn max empire `research_lab` ≥ 4 |
| Override | `game_settings.research_queue_limit` |
| Scheduling | Sequenziell; nach Cancel/Enqueue: `recalculate_research_queue_finish_times()` (GC-510) |
| Finish | `queue_engine.finish_player_research_jobs` |
| Cancel | **GC-831 Refund** (100 % pending / 50 % active); Restqueue neu terminiert |

Migration `008`: `research_queue.start_at` für präzise UI-Fortschritte.  
Kosten-Snapshot auf Row: Migration `076`.

---

## Zeitberechnung

`EffectResolver.get_research_time_seconds()` (GC-825):

- **Basis:** Log-Anker in `economy_balance.research_time_anchor_hours()` (L10 = 1,5 h … L120 = 4320 h)
- **Tech-Tier:** `base_time / 840` (energy_tech = 1,0)
- ÷ Settings: `build_speed` (Default **1.1**), `research_speed` (Default **0.85**)
- ÷ `research_lab_bonus` (+10 %/Level über 1)
- ÷ `research_time_speed` (buildtime_tech, academy +5 %/Level)

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
| `mining_tech`, `drone_tech` | Prod-Faktoren |
| `storage_tech` | `storage_factor` (+25 %/Lvl) |
| `buildtime_tech` | Build + research speed |
| `weapon_tech`, `armor_tech`, `shield_tech` | Combat modifiers → `simulate_battle()` |
| `navigation_tech`, `engine_tech` | `fleet_speed_multiplier` → `fleet.py` / `fleet_calc.py` |
| `fuel_efficiency` | `fuel_efficiency_factor` → `fleet_calc.calculate_fuel_cost()` |

**Not wired:**

| Key | Effekt |
|-----|--------|
| `scan_range` (via `radar_array`) | Kein Scan/Galaxy-Engine |

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

Tech-Tree Visualisierung: `/techtree` (`game/techtree.py`).

---

## UI

- Template: `templates/research.html`
- **Queue-UX (GC-536C):** Status in jeder Tech-Card (`queue_job` via `game/queue_card.py`)
- Kompakt-Header: `#research-queue-compact`
- Poll: `research.techs` + `research.queue` in game-state
- Card-Queue: `GC.renderCardQueueBlock` (domain `research`)

---

## Ship / Building Requirements

- Schiffe: `game/ship_requirements.py` + `fleet_defs`
- Gebäude: `BUILDING_REQUIREMENTS` in buildings.py

---

## Tests

```bash
python -m pytest tests/test_research_requirements.py tests/test_gc825_research_time_rebalance.py tests/test_effects.py tests/test_game_state_live.py tests/test_gc831_queue_refund.py -v
```

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

Account-Forschung verbessert dein **gesamtes Imperium** — Energieeffizienz, Produktion, Flottengeschwindigkeit und Kampfwerte. Kosten zahlst du von der **aktiven Welt**.

## Summary

**Account-Forschung** ist **spielerweit**: ein Tech-Tree mit Queue, Labor-Level über alle Kolonien als Freischalt-Gate, Zahlung in Ferronit/Crytite vom Kontext-Planeten. Sie ist **nicht** Planet Evolution / Planet-Tech — das ist pro Welt ein separates System.

## Why

Forschung löst Engpässe imperiumsweit: mehr Lager, schnellere Bauzeiten, effizientere Minen, mehr Flottenslots, stärkere Waffen. Sie verbindet Economy, Fleet und Combat ohne jeden Planet einzeln zu forcieren.

## How it works

- **Forschungslabor** (mind. Stufe 1 empire-wide max) schaltet Techs frei.
- Starte Forschung auf der Research-Seite; Queue läuft sequenziell (Standard-Limit 2, Bonus bei hohem Labor).
- Techs haben **Voraussetzungen** — Kette planen (Energie vor Antrieb, Extraktion vor Navigation).
- Wichtige Linien: Extraktion, Lager, Bauzeit, Navigation (Flottenslots), Kampf-Technologien.
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

Sprünge nach abgeschlossener Forschung sind normal: jedes Level addiert die **vollen** Level-Kosten zur kumulativen Summe (kein „nur Delta“-Anzeige in der UI).

---

## Commander Tips

- Forschung sollte selten stillstehen — wie Bau-Queue parallel halten.
- Labor auf mindestens einer Welt hoch halten — empire-wide max zählt für Unlocks.
- Tech-Tree-Seite zeigt Abhängigkeiten; priorisiere Engpass-Techs vor Output-Push.

## FAQ

**Warum kann ich eine Tech nicht starten?**
Fehlendes Labor-Level, fehlende Vor-Tech oder nicht genug Ferronit/Crytite auf der aktiven Welt.

**Unterschied Planet-Tech vs. Account-Forschung?**
Account = Imperium. Planet-Tech = nur die gewählte Welt in Planet Evolution.

## Discord Summary

**Account-Forschung — imperiumsweite Technologie**

Ein Tech-Tree für alle Welten: Produktion, Energie, Bauzeit, Navigation, Kampf. Kosten vom aktiven Planeten, Levels account-weit. ≠ Planet-Tech in Planet Evolution. Labor empire-wide max entscheidet Freischaltungen.
