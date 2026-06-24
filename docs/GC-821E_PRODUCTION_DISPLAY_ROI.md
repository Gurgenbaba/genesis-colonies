# GC-821E — Production Display & Long-Term ROI Rebalance

Aligns mine upgrade pacing with **delta production** payback and fixes misleading `+` prefixes in production UI.

| Item | Owner |
|------|--------|
| ROI curves & snapshots | `game/economy_balance.py` |
| Panel / technical payloads | `game/buildings.py` |
| Display (no frontend math) | `static/main.js`, templates |

Production motor unchanged: `game/production_formula.py` · `calculate_resource_output()`.

---

## Display (GC-821E)

- Building cards: **Aktuell / Nach Upgrade / Zuwachs** (`building_effect_strip.html` + `patchBuildingProduction`)
- Technical modal: absolute output per level; `(+Δ/h)` only for real upgrade gain
- Technical modal: **Amortisation** column = server `upgrade_roi_hours`
- Legacy poll: no `+` prefix on absolute `/h` values

---

## ROI definition

```text
payback_hours = upgrade_cost_basis / production_delta_per_hour
```

| Building | Cost basis | Delta resource |
|----------|------------|----------------|
| `metal_mine` | Ferronit cost | Ferronit Δ/h |
| `crystal_mine` | Crytite cost | Crytite Δ/h |
| `fuel_cell_plant` | Ferronit + Crytite | Brennzellen Δ/h |

`production_delta_per_hour` = output(L) − output(L−1) via `reference_production_per_hour()`.

---

## Cost curve (mines only)

GC-821A used `K × level^production_exp` → flat ~4–10 h ROI at all levels.

GC-821E adds long-term pacing on top of a higher cost exponent:

```text
total = K × level^2.05 × (level/20)^1.25 × ((level−80)/40 + 1)^3.40   (level > 80)
```

Constants: `_MINE_COST_EXPONENT`, `_MINE_PACE_GAMMA`, `_MINE_ENDGAME_DELTA` in `economy_balance.py`.

Non-mine buildings keep GC-821 curves.

---

## Target ROI bands (slot 9 reference)

| Level | Target payback |
|-------|----------------|
| L20 | 1–2 h |
| L40 | 4–8 h |
| L60 | 12–24 h |
| L80 | 2–7 days |
| L100 | 2–6 weeks |
| L120 | 1–3 months |

Snapshot table: `balance_snapshot_table()` keys `metal_upgrade_roi_hours`, `production_delta_per_hour`.

Tests: `tests/test_gc821e_production_display_roi.py` (±2× band tolerance).
