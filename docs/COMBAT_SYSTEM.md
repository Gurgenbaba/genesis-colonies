# Combat System — Genesis Colonies

Round-based fleet vs. planet defense battles. Pure simulation in `game/combat.py`; attack arrival orchestration in `game/fleet.py`.

**Status:** ✅ Active (GC-500–GC-510, GC-700A simulator)

---

## Module map

| Module | Role |
|--------|------|
| `game/combat_models.py` | Unit stats registry, `CombatStack`, `stacks_from_counts()`, validation |
| `game/combat.py` | `simulate_battle()`, loot, debris, combat reports |
| `game/combat_simulator.py` | **GC-700A** — player/admin battle simulator (wraps `simulate_battle` only; no DB writes) |
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
4. Each round: surviving lead units refresh shields, then both sides fire from their round-start stacks.
5. Per shot: pick random live target, apply damage (shield then hull), rapid fire chain (cap **64**).
6. Early end only when one side is eliminated; if both sides still stand after round 6, tie-break by remaining firepower; else draw.
7. **Large stacks** (per-type firers &gt; 8 000): same RF rules via aggregate shot counting + bulk HP apply (`_fire_stack_aggregate`) so million-scale fleets stay O(stacks) instead of O(hulls). Small fleets keep the exact per-hull loop.

Research modifiers (per side, additive on explicit overrides):

- `weapon_bonus` → effective attack
- `armor_bonus` → effective hull
- `shield_bonus` → effective shield

Pass `attacker_player_id` / `defender_player_id` (and optional planet ids) to load bonuses via `EffectResolver`.

Deterministic RNG: `battle_rng_for_movement(movement_id)` in fleet tick.

---

## Combat simulator (GC-700A)

Player/admin tool at `/combat-simulator` — **same resolver**, no persistence.

| Endpoint | Role |
|----------|------|
| `GET /combat-simulator` | UI — manual inputs, own-fleet preset only |
| `POST /api/combat-simulator/run` | Single or Monte-Carlo run (`iterations` 1–500) |
| `GET /api/combat-simulator/defaults` | Attacker auto-fill: context planet ships + account research |
| `GET /api/combat-simulator/spy-reports` | Own recent espionage inbox reports (list only) |
| `POST /api/combat-simulator/import-spy-report` | Parse owned spy message metadata → defender payload |

`game/combat_simulator.py`:

- `build_simulation_input()` — sanitize unit maps, tech overrides, resources
- `build_combat_simulator_defaults()` — context planet via `get_context_planet()`, research via `get_research_levels()`
- `list_combat_simulator_spy_reports()` / `import_spy_report_for_simulator()` — inbox metadata only, no live target queries
- `parse_spy_report_metadata_for_defender()` — partial intel (`intel_tiers`), unscanned fields marked
- `run_combat_simulation()` / `run_monte_carlo_simulation()` — call `simulate_battle()` only
- Large fleets use the aggregate shooting path in `combat.py` (O(stacks), not O(hulls); bulk HP apply is O(1) in shot count). Requested Monte-Carlo count is honored up to `MAX_ITERATIONS` (admin default **300**); no hull-based iteration soft-cap
- Client abort: 60s default; **180s** when iterations ≥100 or total units ≥250k
- `summarize_simulation_results()` — win rates, average losses/debris/loot, sample report
- Loot preview uses `calculate_plunder_pool()` + `load_resources_up_to_cargo()` (no planet debit)
- Admin balancing mode: default 300 iterations, unit efficiency table, CSV/JSON copy

Forbidden: duplicate combat math in JS; DB writes; fleet movements; inbox messages.

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
  → maybe colony destroy (GC-P24/P31) # non-homeworld + breaker + full wipe (AI or human)
  → return flight with surviving ships (+ resources_json if loot)
```

Colony destroy (owner `game/pirates/destroy.py`): any **non-homeworld** colony after attacker win, empty defender hangar+defense, and at least one surviving `planet_breaker` (consumed). AI wipe raises faction bounty + heat + recolonize cooldown; human wipe raises attacker threat and logs `colony_destroyed`. Homeworlds are never destroyable.
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

Debris: stored in `debris_fields` at target coordinates; shown in galaxy system view ([GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)). TTL (`DEBRIS_FIELD_TTL_SECONDS`, 7 days from `updated_at`) is **hard expire** via `expire_due_debris_fields` (fleet-worker piggyback + defensive purge on galaxy/harvest reads). Zero-amount rows are deleted on harvest.

---

## Reports

- `build_combat_report()` → structured metadata + localized body
- Both attacker and defender receive inbox messages (`dispatch_combat_reports`)
- UI: `static/js/messages.js` → `renderCombatReportTeaser` / `renderCombatReportFull` (modal)
- **GC-700E:** coord links + attack CTA, always-on loot panel (empty state), `combat_kind` badges (pirate / world boss), dead `renderCombatBattleOverview` removed
- **Recycler CTA:** one-click send of `recycler_slots_needed` via `GC.GalaxyQuickAction.sendDebrisRecycle` (same owner as Galaxy debris)

---

## Ranking hooks

After combat: `record_combat_outcome()` updates `score_destroyed_raw`; `compute_military_score()` combines fleet + defense + destroyed ([scoring.py](../game/scoring.py)).

---

## Ship combat roles (balance owner: `game/fleet_defs.py`)

Canonical combat stats live only in `fleet_defs.SHIPS` / `defense_defs.DEFENSES`. `combat_models.combat_stats_for_ship()` and the Battle Lab simulator read those defs — no JS combat math.

| Hull | Role | Notes |
|------|------|--------|
| `spark_drone` (Vanguard Scout) | Light striker / screen | High attack per cost, low hull; RF vs `veil_probe`; countered by Raptor Interceptor RF + Flak Array |
| `falcon_interceptor` (Raptor Interceptor) | Allrounder fighter | RF vs scouts/spy; not best DPS/cost or best vs equal-cost defense |
| `ironclad_frigate` (Aegis Frigate) | Heavy puncher / anti-defense | RF vs light ships + Sentinel Turret / Plasma Arc; slower, fuel-heavy |
| Cargo / expo / colony hulls | Non-combat | Minimal or zero attack — not tuned as fleet DPS |

Mass single-ship stacks are intentionally avoided: mixed fleets and planet defense remain viable at similar resource budgets.

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
| Shield-only damage | No unit loss until hull reaches 0; surviving lead-unit shields refresh each round |

---

## Tests

Combat balance is validated **locally via pytest** (no live in-game bot fights required):

```bash
python -m pytest tests/test_combat.py -k balance -v
python -m pytest tests/test_combat_balance_bots.py -v
python -m pytest tests/test_combat.py -v
python -m pytest tests/test_combat_simulator.py -v
python -m pytest tests/test_fleet.py -k "attack or combat or debris or loot" -v
python -m pytest tests/test_ranking.py::test_combat_destruction_increases_ranking_scores -v
```

Live combat-balance bot accounts (`gc_combat_bot_alpha` / `beta`) and cron automation are **paused** (`LIVE_IN_GAME_BOTS_ENABLED = False` in `game/combat_balance_bots.py`) until a real bot-player mechanic ships.

---

## Related docs

- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — missions, tick, return flights
- [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) — defense stock, spy intel
- [EFFECTS.md](EFFECTS.md) — combat tech modifiers
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — debris display

---

## Player Article

```yaml
---
codex_id: combat
band: III
difficulty: intermediate
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
routes:
  - fleet_view
related_codex:
  - fleet
  - defense
  - research
terminology: GENESIS_TERMINOLOGY
unlock:
  type: player_flag
  flag: first_fleet_sent
teaser_key: codex_unlock_combat_teaser
---
```

## Quick Help

Kampf entsteht, wenn eine **Angriff**-Flotte an einer verteidigten Welt ankommt: Flotte vs. Hangar und planetare Verteidigung — Berichte für beide Seiten.

## Summary

Combat ist **rundenbasiert** (bis zu sechs Runden): Angreifer-Flotte gegen Verteidiger-Hangar plus **stationäre Verteidigung** am Ziel-Planeten. Ergebnis: Verluste, Trümmerfeld, optional Plunder für den Sieger, Kampfberichte in Nachrichten. Forschung (`weapon_tech`, `armor_tech`, `shield_tech`) modifiziert Kampfwerte.

## Why

PvP und Risiko auf Kolonien brauchen klare, serverseitige Resolution — kein Client-Math. Kampf koppelt Fleet, Defense, Research und Ranking (militärischer Score).

## How it works

- Sende **attack**-Mission von der Fleet-Seite gegen fremde oder eigene Testziele (PvP-Regeln beachten).
- Wähle Ziel per Quick-Target, Koordinaten oder Galaxie-Link — Server berechnet Flugzeit und Brennzellen.
- Bei Ankunft: Simulation → Verluste auf Flotte, `planet_ships`, `planet_defense`.
- **Sieger Angreifer:** Plunder bis Frachtraum der zurückkehrenden Flotte; Gutschrift bei Rückkehr (nicht sofort am Ziel).
- **Trümmerfeld** am Zielkoordinaten — sichtbar in Galaxie-Systemansicht; `recycle`-Mission kann bergen.
- Beide Spieler erhalten **Kampfberichte** (strukturierte Inbox) mit Runden, Verlusten und Ergebnis.
- **Verteidigung** (stationär) und **Hangar-Schiffe** kämpfen gemeinsam — nur Hangar reicht nicht.
- Kampf-Techs (`weapon_tech`, `armor_tech`, `shield_tech`) modifizieren Werte imperiumsweit.
- Kampfformeln und Einzelwerte: nicht im Codex — Schiff/Defense-Detail und Technische Daten.

## Related Systems

- fleet
- defense
- research
- galaxy

## Commander Tips

- Kampf-Techs vor dem ersten Angriff — sie wirken auf die gesamte Flotte bzw. Verteidigung.
- Verteidigung am Planeten zählt mit — nicht nur Schiffe im Hangar.
- Plunder ist begrenzt durch Rückkehr-Cargo, nicht durch unendlichen Raub.

## FAQ

**Wann sehe ich den Kampf-Guide?**
Nach der ersten gesendeten Flotte (Unlock) — oder sobald Angriff relevant wird.

**Sofortiger Sieg ohne Runden?**
Wenn eine Seite keine Kampfeinheiten hat — technisch 0 Runden.

## Discord Summary

**Kampf — Angriff-Flotte vs. Planet**

Rundenbasierter Resolver, max. 6 Runden. Verluste, Trümmer, Plunder für Sieger. Berichte an beide Seiten. Research-Modifikatoren. Trümmer in Galaxie sichtbar.
