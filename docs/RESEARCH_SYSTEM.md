# Research System

Account-weite Technologie-Forschung (v1.5.3).

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

Jede Tech: `base_cost_m/c`, `base_time`, `cost_factor`, verschachtelte Tech-Requirements.

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
| Cancel | Kein Refund; Restqueue wird neu terminiert |

Migration `008`: `research_queue.start_at` für präzise UI-Fortschritte.

---

## Zeitberechnung

`EffectResolver.get_research_time_seconds()`:

- Basis × `cost_factor^(level-1)`
- ÷ Settings: `build_speed`, `research_speed`
- ÷ `research_lab_bonus` (+10%/Level über 1)
- ÷ `research_time_speed` (buildtime_tech, academy)

---

## EffectResolver-Integration

**Aktiv (Economy/Time):**

| Tech | Effekt |
|------|--------|
| `energy_tech` | `mine_energy_factor` |
| `mining_tech`, `drone_tech` | Prod-Faktoren |
| `storage_tech` | `storage_factor` |
| `buildtime_tech` | Build + research speed |

**Prepared (noch kein Consumer):**

`weapon_tech`, `armor_tech`, `shield_tech` → Combat modifiers  
`navigation_tech`, `engine_tech` → `fleet_speed_multiplier` (prepared in resolver)  
`fuel_efficiency` → `fuel_efficiency_factor` (active — `fleet_calc.calculate_fuel_cost`)

Details: [EFFECTS.md](EFFECTS.md) — prepared modifiers **nicht** als aktiv bewerben.

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
- **Queue-UX (GC-536C):** Status in jeder Tech-Card (`queue_job` via `game/queue_card.py` + `_attach_queue_jobs_to_research_techs`)
- Kompakt-Header: `#research-queue-compact` — nur Zähler (`🔬 N Forschungen aktiv`)
- Chip: empire lab level
- Poll: `research.techs` + `research.queue` in game-state
- Card-Queue: `GC.renderCardQueueBlock` (domain `research`) / `.gc-card-queue-block--research`

---

## Ship / Building Requirements

- Schiffe: `game/ship_requirements.py` + `fleet_defs`
- Gebäude: `BUILDING_REQUIREMENTS` in buildings.py

---

## Tests

```bash
python -m pytest tests/test_research_requirements.py tests/test_effects.py tests/test_game_state_live.py -v
```
