# Combat System — Genesis Colonies

Round-based fleet vs. planet defense battles. Pure simulation in `game/combat.py`; attack arrival orchestration in `game/fleet.py`.

**Status:** ✅ Active (GC-500–GC-510)

---

## Module map

| Module | Role |
|--------|------|
| `game/combat_models.py` | Unit stats registry, `CombatStack`, `stacks_from_counts()`, validation |
| `game/combat.py` | `simulate_battle()`, loot, debris, combat reports |
| `game/fleet.py` | Attack arrival → simulate, apply losses, loot, debris, ranking, return |
| `game/fleet_defs.py` / `game/defense_defs.py` | Raw combat values + rapid fire |
| `game/effects/effect_resolver.py` | `weapon_tech`, `armor_tech`, `shield_tech` → side modifiers |
| `game/messages.py` | Inbox dispatch, `normalize_combat_metadata()` |
| `game/scoring.py` | `record_combat_outcome()`, military score |
| `game/resources.py` | Plunder pool, cargo load, planet debit |

---

## Battle engine (`simulate_battle`)

Inputs are **not mutated**; no DB side effects.

1. Build `_UnitState` per stack (shield/hull per lead unit).
2. Early exit: both empty → draw; one side empty → other side wins (no rounds).
3. Up to **6 rounds** (`DEFAULT_MAX_ROUNDS`); `max_rounds` is clamped to `[1, 6]`.
4. Each round: attacker shoots → defender shoots.
5. Per shot: pick random live target, apply damage (shield then hull), rapid fire chain (cap **64**).
6. Winner: side with units left; tie-break by remaining firepower; else draw.

Research modifiers (per side, additive on explicit overrides):

- `weapon_bonus` → effective attack
- `armor_bonus` → effective hull
- `shield_bonus` → effective shield

Pass `attacker_player_id` / `defender_player_id` (and optional planet ids) to load bonuses via `EffectResolver`.

Deterministic RNG: `battle_rng_for_movement(movement_id)` in fleet tick.

---

## Attack arrival flow (`fleet.py`)

```
process_fleet_tick → attack arrival
  → simulate_battle(attacker stacks, defender hangar + planet_defense)
  → apply losses to planet_ships / planet_defense / returning fleet
  → spawn_combat_debris_at_planet()
  → record_combat_outcome()          # destroyed_raw for ranking
  → apply_combat_loot()              # if attacker wins
  → apply_score_updates_for_players()
  → publish_attack_combat_report()   # both players, COMBAT_REPORT_VERSION=2
  → return flight with surviving ships (+ resources_json if loot)
```

---

## Balance constants

| Constant | Value | Notes |
|----------|-------|-------|
| `DEFAULT_MAX_ROUNDS` | 6 | Hard cap on rounds |
| `_MAX_RF_CHAIN` | 64 | Rapid-fire recursion limit |
| `COMBAT_PLUNDER_FRACTION` | 0.5 | Max stealable pool per resource |
| `DEBRIS_METAL_FRACTION` | 0.3 | Of build cost (metal) |
| `DEBRIS_CRYSTAL_FRACTION` | 0.3 | Of build cost (crystal) |

Loot: winner loads plunder up to **returning fleet cargo** (metal → crystal → fuel_cells). Credited on return tick at home planet.

Debris: stored in `debris_fields` at target coordinates; shown in galaxy system view ([GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)).

---

## Reports

- `build_combat_report()` → structured metadata + localized body
- Both attacker and defender receive inbox messages
- UI: `static/js/messages.js` → `renderCombatReport()`

---

## Ranking hooks

After combat: `record_combat_outcome()` updates `score_destroyed_raw`; `compute_military_score()` combines fleet + defense + destroyed ([scoring.py](../game/scoring.py)).

---

## Edge cases (handled)

| Case | Outcome |
|------|---------|
| Both sides empty | Draw, 0 rounds |
| Attacker empty | Defender wins, 0 rounds |
| Defender empty (no hangar/defense) | Attacker wins, 0 rounds |
| Unknown unit keys in stock maps | Skipped by `stacks_from_counts()` |
| `max_rounds=0` while fighting | Still runs 1 round (clamped) |
| Non-combat ships (0 attack) | Contribute hull only; may extend to draw at round cap |
| Shield-only damage | No unit loss until hull reaches 0 |

---

## Tests

```bash
python -m pytest tests/test_combat.py -v
python -m pytest tests/test_fleet.py -k "attack or combat or debris or loot" -v
python -m pytest tests/test_ranking.py::test_combat_destruction_increases_ranking_scores -v
```

---

## Related docs

- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — missions, tick, return flights
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) — defense stock, spy intel
- [EFFECTS.md](EFFECTS.md) — combat tech modifiers
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — debris display
