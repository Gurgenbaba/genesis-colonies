# GC-821F — Long-Term Mine ROI & Bulk Upgrade Readiness

Extends GC-821E with **slower early/mid** pacing and **~2000 h** payback at L120 (neutral slot).

| Item | Owner |
|------|--------|
| ROI anchors & cost scaling | `game/economy_balance.py` |
| Bulk upgrade prep | `mine_bulk_upgrade_preview()`, `MINE_BULK_UPGRADE_INCREMENTS` |
| Technical data bulk meta | `build_building_technical_data()` → `bulk_upgrade` |

Production unchanged: `calculate_resource_output()`.

---

## ROI anchors (metal mine, slot 9)

| Level | Target payback |
|-------|----------------|
| L20 | 50 h |
| L40 | 100 h |
| L60 | 200 h |
| L80 | 500 h |
| L100 | 1000 h |
| L120 | 2000 h |

Between anchors: **log-linear** interpolation (`mine_roi_anchor_hours`).

Cost scaling: 821E base × `mine_roi_cost_multiplier(level)` (same factor for all mine types).

ROI source: `mine_upgrade_roi_hours()` — cost basis / `production_delta_per_hour`.

---

## Bulk upgrade (prep only)

```python
MINE_BULK_UPGRADE_INCREMENTS = (1, 5, 10)
mine_bulk_upgrade_preview(building, from_level, max_level, metal=…, crystal=…)
```

Returns options for +1 / +5 / +10 / max affordable — **UI buttons follow-up ticket**.

---

## Bugfix (GC-823)

Technical modal JS used undefined `fmtNumberCompact` → `formatNumberCompact` (caused “Technische Daten konnten nicht geladen werden” after successful API response).

---

## Tests

```bash
python -m pytest tests/test_gc821f_mine_roi_bulk.py tests/test_gc821e_production_display_roi.py -v
```
