# GC-862 — Buildings Resolver Reuse & Queue Hotpath Optimization

**Status:** DONE

## Root Cause

Three buildings hotpaths recreated `EffectResolver` and reloaded planet state on every inner iteration:

1. `build_building_technical_data()` — per preview level
2. `recalculate_build_queue_finish_times()` — per queue row
3. `queue_build_for_planet()` MAX mode — per enqueue attempt

## Fix

Extended existing `BuildingsPanelContext` (GC-854, no parallel system):

| Method | Purpose |
|--------|---------|
| `for_queue_recalc()` | One resolver for recalc / MAX enqueue |
| `build_time_seconds()` | Cached `(building_type, target_level)` |
| `build_time_seconds_at_target()` | Cached bumped-level build times |
| `resolver_at_target()` | Cached bumped `EffectResolver` instances |

### `build_building_technical_data()`

Single `BuildingsPanelContext.for_planet()` → shared across all preview rows.

### `recalculate_build_queue_finish_times()`

Single `for_queue_recalc()` → cached build times per row.

### `queue_build_for_planet()` MAX

Load buildings/research/queue once; track `rows_db`, resources, `queued_same` locally after each enqueue.

## Changed Files

- `game/buildings.py`
- `tests/test_gc862_buildings_hotpath_optimization.py`
- `docs/GC-862_BUILDINGS_HOTPATH_OPTIMIZATION.md`

## Tests

```bash
python -m pytest tests/test_gc862_buildings_hotpath_optimization.py tests/test_gc850a_build_time_wiring.py tests/test_race_conditions.py tests/test_queue_static_contract.py -q
```

## Perf Before/After (expected)

| Path | Before | After |
|------|--------|-------|
| Technical data (L0–L5 preview) | ~6+ `get_effect_resolver` | **1** |
| Recalc 3 jobs | 3 resolver builds | **1** + cache hits |
| MAX queue N jobs | N× (buildings + research + queue reads) | **1× each** + local state |

## Ergebnis

| Item | Verdict |
|------|---------|
| Balance / queue rules | unchanged |
| Technical data output | identical |
| Queue times / MAX results | identical |
| DB reads in MAX loop | **reduced** |

## Related

- GC-854 — `BuildingsPanelContext` (SSR panel)
- GC-861 — LCP / assets (orthogonal)
