# Production Formula System (GC-820 / Ferdi-Rebase)

**Single source of truth** for all resource production in Genesis Colonies.

| Item | Owner |
|------|--------|
| Implementation | `game/production_formula.py` |
| Integration / tick | `game/effects/effect_resolver.py` → `game/resources.py` |
| Energy (supply/demand) | `EffectResolver.compute_energy()` — throttles **mine output only** |

---

## Architecture

```
ProductionContext (inputs)
        ↓
ProductionModifiers (per-factor multipliers)
        ↓
calculate_resource_output(resource_type, context)  →  output / hour
        ↓
EffectResolver.production_rates_per_sec(energy_ratio)  →  ÷ 3600 for tick
```

New gameplay systems **register modifiers** on `ProductionContext` or extend `ProductionModifiers`. Modifier hooks stay stable; base curve = standard income + mine exponential (Ferdi-Rebase).

Forbidden: second production engines, frontend production math, hidden level softcaps, stacked exponential tiers beyond the canonical base.

---

## Formula

All resources:

```text
Output/h

  = StandardBase × production_speed × modifiers (excl. energy)
  + MineBase × level × 1.075^level × production_speed × modifiers (incl. energy on mine part)
```

### Standard production (every planet)

| Resource | Key | Standard / h |
|----------|-----|--------------|
| Ferronit | `metal` | 15 000 |
| Crytite | `crystal` | 10 000 |
| Brennzellen | `fuel_cells` | 5 000 |

Runs without mines. **Not** reduced by energy shortage (baseline supply).

Constants: `STANDARD_PRODUCTION_PER_HOUR` in `game/production_formula.py`.

### Mine growth (Ferdi-Rebase)

| Resource | Key | Mine base | Formula |
|----------|-----|-----------|---------|
| Ferronit | `metal` | 150 | `150 × level × 1.075^level` |
| Crytite | `crystal` | 100 | `100 × level × 1.075^level` |
| Brennzellen | `fuel_cells` | 50 | `50 × level × 1.075^level` |

Level 0 mine → no mine output (standard still applies).

Central helpers: `standard_output()`, `mine_output()` / `ferdi_base_output()` in `game/production_formula.py`.

`production_speed` = admin `production_speed` setting (default 1.0).

### Modifier order

Applied as a single product per part (order commutative). Convention in code:

1. Slot (galaxy position)
2. Temperature (fuel only)
3. Research
4. Energy (**mine part only**)
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

Under-supply reduces **mine** production only; standard production stays at full modifier stack (excl. energy).

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

Regenerate from code:

```bash
python scripts/gen_anchor_tables.py docs/GC_ANCHOR_TABLES_X1.md
```

Vollständige Ankertabellen: [GC_ANCHOR_TABLES_X1.md](GC_ANCHOR_TABLES_X1.md)

---

## Balancing goals

| Stage | Level | Intent |
|-------|-------|--------|
| Early | 10 | Fast baseline via standard income; mines add on top |
| Mid | 30 | Comfortable progression |
| Strong | 60 | High output |
| High-end | 90 | Endgame ramp (not inflated by flat +365 offset) |
| Cap | 120 | Maximum mine levels (requires nexus extensions above L50) |

---

## Examples

**No mine (L0), slot 9:** Ferronit **15 000 / h**, Crytite **10 000 / h**, Brennzellen **5 000 / h**.

**Level 10 Ferronit mine, slot 5 (+16 % slot), mining L10 (+30 %), energy 80 %:**

```text
15 000 × 1.16 × 1.30 + (150 × 10 × 1.075^10) × 1.16 × 1.30 × 0.80
```

---

## Consumers

| Consumer | Usage |
|----------|--------|
| `EffectResolver.production_rates_per_sec` | Resource tick |
| `EffectResolver.get_building_production_per_hour` | Overview, buildings, `/api/game-state` |
| `game/resources.update_planet_resources` | Applies `energy_ratio` at tick (mine-only throttle) |
| `game/inventory_loot.py` | Scaled rewards from production |

---

## Forbidden patterns

- Duplicate formulas in `buildings.py`, `static/`, or feature modules
- Legacy `base × level^exponent + 365` additive offset
- Level-based softcaps (L50 bonus, L120 cap) in production
- Frontend `production_per_hour` calculation as truth
- Parallel `production_engine` modules

---

## Tests

```bash
python -m pytest tests/test_production_formula.py tests/test_effects.py tests/test_game_state_live.py -v
```
