# GC-821 — Economy Rebalance after GC-820

Consumer rebalance pass — **does not change** `calculate_resource_output()` or `production_formula.py`.

| Item | Owner |
|------|--------|
| Balance curves & snapshots | `game/economy_balance.py` |
| Production (unchanged) | `game/production_formula.py` |

---

## Principle

GC-820 production grows as **power scaling** (`level^exp`).  
Pre-GC-821 building costs used **exponential** factors (`1.5^level`) — at L60+ upgrades became unaffordable.

GC-821 aligns upgrade **costs** and **build times** to the same power-law family as production.

---

## GC-821A — Buildings, Costs & Build Times

**Formula:**

```text
upgrade_cost ≈ K × target_level^exponent
build_seconds ≈ TIME_K × target_level^1.35
```

Exponents for mines match `LEVEL_GROWTH` in `production_formula.py`.

**Result (GC-821A):** Ferronit mine upgrade ~4–10 h of Ferronit production across L10–L120 (slot 9 reference).

**GC-821E** replaces flat ROI with delta-based payback and endgame pacing — see `docs/GC-821E_PRODUCTION_DISPLAY_ROI.md`.

**GC-821F** stretches early/mid ROI (L20 ≈ 50 h, L120 ≈ 2000 h) via anchor multipliers — see `docs/GC-821F_MINE_ROI_BULK.md`.

Curves: `BUILDING_UPGRADE_CURVES`, `BUILD_TIME_CURVES` in `economy_balance.py`.  
Wired via `buildings.get_upgrade_cost()` / `power_build_seconds()`.

---

## GC-821B — Storage, Trader & Exchange

| Constant | Was | GC-821 |
|----------|-----|--------|
| `BASE_STORAGE` | 100 000 | 150 000 |
| `STORAGE_GROW` | 1.8 | 1.75 |
| `exchange_daily_limit_min` | 25 M | 500 000 |

Trader limit still: `empire_day_total × pct / 100` (auto-scales with GC-820 production).

---

## GC-821C — Expedition, Rewards & Loot

| Constant | Was | GC-821 |
|----------|-----|--------|
| `LOOT_RESOURCE_FLOOR_MIN` | 5 000 | 12 000 |
| `LOOT_RESOURCE_FLOOR_MAX` | 10 000 | 30 000 |

Mine-scaled loot still uses `empire_resource_production_per_hour()` → GC-820.  
Expedition `economy_day_range` % bands unchanged (already empire-relative).

---

## GC-821D — Shipyard, Defense, Ranking & Admin

- Fleet hull `build_cost` × **1.25** (GC-820 income alignment)
- Defense `build_cost` × **1.25**
- `score_value` unchanged (cost tables drive ranking)
- `fuel_production_per_hour` admin key **deprecated** — display only; fuel uses `LEVEL_GROWTH` base 8.0

---

## Balance snapshot (slot 9, `production_speed` 1)

Use `balance_snapshot_table()` in `economy_balance.py` or:

```bash
python -c "from game.economy_balance import balance_snapshot_table; import pprint; pprint.pp(balance_snapshot_table())"
```

| Level | Ferronit/h | Upgrade Ferronit cost | Metal-hours |
|-------|------------|----------------------|-------------|
| 10 | ~852 | ~1 100 | ~4 h |
| 30 | ~4 675 | ~6 100 | ~4 h |
| 60 | ~13 688 | ~17 800 | ~4 h |
| 90 | ~25 662 | ~33 400 | ~4 h |
| 120 | ~40 081 | ~52 200 | ~4 h |

(Power-law costs yield near-constant afford time vs polynomial production.)

---

## Forbidden

- Second production engine
- Changing `calculate_resource_output()` in GC-821 scope
- Re-enabling `fuel_production_per_hour` as production source

---

## Tests

```bash
python -m pytest tests/test_gc821_economy_rebalance.py tests/test_production_formula.py -v
```
