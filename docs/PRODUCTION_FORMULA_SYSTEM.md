# Production Formula System (GC-820 / GC-860)

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

New gameplay systems **register modifiers** on `ProductionContext` or extend `ProductionModifiers`. Modifier hooks stay stable; only the base level curve changed in GC-860.

Forbidden: second production engines, frontend production math, hidden level softcaps, stacked exponential tiers beyond the canonical Ferdi base.

---

## Formula

All resources:

```text
Output/h

  = (multiplier × level × 1.075^level + 365)
  × production_speed
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

### Level growth (Ferdi base — GC-860)

| Resource | Key | Multiplier |
|----------|-----|------------|
| Ferronit | `metal` | 100 |
| Crytite | `crystal` | 66 |
| Brennzellen | `fuel_cells` | 33 |

Shared constants: growth rate **1.075**, flat offset **+365** per hour.

Central helper: `ferdi_base_output(resource_type, level)` in `game/production_formula.py`.

`production_speed` = admin `production_speed` setting (default 1.0).

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
| `directive_modifier` | Climate prod overlay + Galactic Directives + Diplomacy |
| `event_modifier` | Global / expedition events |
| `season_modifier` | Seasons, anomalies, premium |

---

## Snapshot values (slot 9, speed 1, no research, full energy)

Pure formula benchmark — **excludes** climate/GD/diplomacy overlay on `directive_modifier`. Brennzellen include slot-9 temperature modifier. Live colonies may differ slightly.

| Level | Ferronit/h | Crytite/h | Brennzellen/h |
|-------|------------|-----------|---------------|
| 1 | 473 | 436 | 460 |
| 10 | 2 426 | 1 725 | 1 202 |
| 30 | 26 630 | 17 700 | 10 384 |
| 60 | 460 260 | 303 896 | 174 903 |
| 90 | 6 039 911 | 3 986 465 | 2 291 807 |
| 120 | 70 501 638 | 46 531 205 | 26 748 410 |

Vollständige Ankertabellen: [GC_ANCHOR_TABLES_X1.md](GC_ANCHOR_TABLES_X1.md) · Regenerieren: `python scripts/gen_anchor_tables.py docs/GC_ANCHOR_TABLES_X1.md`

---

## Balancing goals

| Stage | Level | Intent |
|-------|-------|--------|
| Early | 10 | Noticeable growth |
| Mid | 30 | Comfortable progression |
| Strong | 60 | High output |
| High-end | 90 | Endgame ramp |
| Cap | 120 | Maximum mine levels (requires nexus extensions above L50) |

Target readable ranges: millions → billions → low trillions. Avoid quadrillions in normal play.

---

## Examples

**Level 30 Ferronit, slot 5 (+16 % slot), mining L10 (+30 %), energy 80 %:**

```text
26 630 × 1.16 × 1.30 × 0.80 ≈ 32 100 / h
```

**Level 60 Brennzellen, slot 15 (+20 % slot, +35 % temp cap), drone L5 (+10 %):**

```text
174 903 × 1.20 × 1.35 × 1.10 ≈ 311 500 / h
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
- Legacy `base × level^exponent` power scaling (replaced GC-860)
- Level-based softcaps (L50 bonus, L120 cap) in production
- Frontend `production_per_hour` calculation as truth
- Parallel `production_engine` modules

---

## Tests

```bash
python -m pytest tests/test_production_formula.py tests/test_effects.py tests/test_game_state_live.py -v
```
