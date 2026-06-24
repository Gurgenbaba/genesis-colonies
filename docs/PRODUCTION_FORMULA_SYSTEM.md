# Production Formula System (GC-820)

**Single source of truth** for all resource production in Genesis Colonies.

| Item | Owner |
|------|--------|
| Implementation | `game/production_formula.py` |
| Integration / tick | `game/effects/effect_resolver.py` → `game/resources.py` |
| Energy (supply/demand) | `EffectResolver.compute_energy()` — not part of level growth |

---

## Architecture

```
ProductionContext (inputs)
        ↓
ProductionModifiers (per-factor multipliers)
        ↓
calculate_resource_output(resource_type, context)  →  output / hour
        ↓
EffectResolver.production_rates_per_sec()  →  ÷ 3600 for tick
```

New gameplay systems **register modifiers** on `ProductionContext` or extend `ProductionModifiers`. The base formula never changes.

Forbidden: second production engines, frontend production math, hidden level softcaps, stacked exponentials (`level × 1.1^level`, bonus tiers at L50/L120).

---

## Formula

All resources:

```text
Output/h

  = Base × speed × level^exp
  × SlotModifier
  × TemperatureModifier
  × ResearchModifier
  × EnergyModifier
  × BuildingModifier
  × PlanetModifier
  × EmpireModifier
  × AllianceModifier
  × DirectiveModifier
  × EventModifier
  × SeasonModifier
```

### Level growth (power scaling)

| Resource | Key | Base | Exponent |
|----------|-----|------|----------|
| Ferronit | `metal` | 24 | 1.55 |
| Crytite | `crystal` | 16 | 1.50 |
| Brennzellen | `fuel_cells` | 8 | 1.42 |

`speed` = admin `production_speed` setting (default 1.0).

### Modifier order

Applied as a single product (order commutative). Convention in code:

1. Slot (galaxy position)
2. Temperature (fuel only)
3. Research
4. Energy
5. Building / Planet / Empire / Alliance / Directive / Event / Season

### Slot bonuses

| Resource | Galaxy slots | Max bonus |
|----------|--------------|-----------|
| Ferronit | 4–9 | +20 % (peak slot 4) |
| Crytite | 1–3 | +25 % (peak slot 1) |
| Brennzellen | 10–15 | +20 % (peak slot 15) |

Outside range: factor `1.0`. Linear interpolation within range.

### Temperature (Brennzellen only)

- Range: **0.75 … 1.35** (hard clamp)
- Hot worlds → lower; cold worlds → higher
- Mapped from galaxy slot mid-temperature (slot 1 ≈ 0.75, slot 15 ≈ 1.35)

### Research

| Tech | Effect |
|------|--------|
| `mining_tech` | +3 % Ferronit per level (multiplicative) |
| `drone_tech` | +2 % Ferronit + Crytite per level |
| `buildtime_tech` | Build/research time only — **no** production |

### Energy

```text
energy_ratio = min(1, energy_available / energy_required)
```

Under-supply reduces production; over-supply does **not** boost above 100 %.

Galaxy climate still adjusts **solar output** via `EffectResolver` (`solar_output_factor`); mine output uses slot/temperature modifiers above.

### Extension points (default 1.0)

| Modifier | Future use |
|----------|------------|
| `building_modifier` | Per-building production bonuses |
| `planet_modifier` | Planet classes |
| `empire_modifier` | Imperium doctrines |
| `alliance_modifier` | Alliance bonuses |
| `directive_modifier` | Galactic Directives + Diplomacy overlay |
| `event_modifier` | Global / expedition events |
| `season_modifier` | Seasons, anomalies, premium |

---

## Snapshot values (slot 8, speed 1, no research, full energy)

| Level | Ferronit/h | Crytite/h | Brennzellen/h |
|-------|------------|-----------|---------------|
| 1 | 24 | 16 | 8 |
| 10 | 852 | 506 | 211 |
| 30 | 3 968 | 2 629 | 942 |
| 60 | 11 729 | 7 437 | 2 591 |
| 90 | 19 236 | 13 670 | 4 434 |
| 120 | 25 932 | 21 046 | 6 236 |

Snapshot uses **galaxy slot 9** (no slot bonus for any resource at reference levels).

With `production_speed = 400` (live tuning), multiply by 400 for admin-boosted benchmarks.

---

## Balancing goals

| Stage | Level | Intent |
|-------|-------|--------|
| Early | 10 | Noticeable growth |
| Mid | 30 | Comfortable progression |
| Strong | 60 | High output |
| High-end | 90 | Endgame ramp |
| Cap | 120 | Maximum mine levels |

Target readable ranges: millions → billions → low trillions. Avoid quadrillions in normal play.

---

## Examples

**Level 30 Ferronit, slot 5 (+16 % slot), mining L10 (+30 %), energy 80 %:**

```text
3 968 × 1.16 × 1.30 × 0.80 ≈ 4 790 / h
```

**Level 60 Brennzellen, slot 15 (+20 % slot, +35 % temp cap), drone L5 (+10 %):**

```text
2 591 × 1.20 × 1.35 × 1.10 ≈ 4 612 / h
```

---

## Consumers

| Consumer | Usage |
|----------|--------|
| `EffectResolver.production_rates_per_sec` | Resource tick |
| `EffectResolver.get_building_production_per_hour` | Overview, buildings, `/api/game-state` |
| `game/resources.update_planet_resources` | Applies `energy_ratio` at tick |
| `game/inventory_loot.py` | Scaled rewards from production |

---

## Forbidden patterns

- Duplicate formulas in `buildings.py`, `static/`, or feature modules
- `level × 1.1^level` or multiple exponential tiers
- Level-based softcaps (L50 bonus, L120 cap) in production
- Frontend `production_per_hour` calculation as truth
- Parallel `production_engine` modules

---

## Tests

```bash
python -m pytest tests/test_production_formula.py tests/test_effects.py tests/test_game_state_live.py -v
```
