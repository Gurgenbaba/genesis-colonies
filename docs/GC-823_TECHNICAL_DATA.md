# GC-823 / GC-823B — Technical Data 2.0

Server-built `display` blocks and `summary` for building/research technical modals. No frontend game math.

| Item | Owner |
|------|--------|
| Display payloads, level schedule, summaries | `game/technical_data.py` |
| Building API | `game/buildings.py` → `build_building_technical_data` |
| Research API | `game/research.py` → `build_research_technical_data` |
| Modal renderer | `static/main.js` → `renderBuildingTechnicalTable` |

Production authority unchanged: `calculate_resource_output()`, ROI from live planet context.

---

## Modal structure (GC-828)

1. **Nächstes Upgrade** — `summary`: Aktuell / Nach Upgrade / Zuwachs / Amortisation (+ Kosten, Bau-/Forschungszeit).
2. **Aktive Boni** — `summary.active_bonuses` (mines: slot/research/empire; research: lab/nanofactory/buildtime; yard: production bonuses).
3. **Meilensteine** — `milestones` (mines: `build_production_milestones`; research: `build_research_effect_milestones`).
4. **Stufenübersicht** — layout-specific table; `resolve_technical_table_layout` picks layout from any row (not only L0).

Ship/defense unit modals: `build_unit_technical_block` in `technical_data.py` → `templates/partials/unit_technical_detail.html` (build preview, combat stats, combat research bonuses).

---

## Modal structure (2.0, legacy note)

1. **Summary (top)** — `data.summary`: Aktuell / Nach Upgrade / Zuwachs / Amortisation (research: research duration as ROI hours). At max level: `at_max_level` + `technical_max_level_reached`.
2. **Active bonuses (mines)** — slot, research, empire, energy, events from `summary.active_bonuses` + formula collapsible.
3. **Level table (bottom)** — layout-specific columns; row badges via `row_role`: `current`, `next`, `milestone`, `preview`.

### Level schedule (`technical_preview_levels`)

- **Early game** (`current ≤ 5`): rows `L0 … L5`
- **Midgame+**: `current`, `next` (`current + 1`), then milestones `10, 20, 30, …, 120` above next

---

## Table layouts (`table_layout`)

| Layout | Columns | Example |
|--------|---------|---------|
| `production` | Level, Produktion/h, Δ Produktion, Energie, Δ Energie, ROI | Mines |
| `effect_percent` | Level, Verbrauch/Effekt, Δ | Energieeffizienz (100 % → 95 %), Forschung |
| `yard` | Level, Kapazität, Bauzeit, ROI | Orbitalwerft |
| `storage` | Level, Kapazität, Δ | Depots (`+0` or max-level hint) |
| `energy` | Level, Erzeugung, Δ | Solarkraftwerk |

Energy mines: `energy_at_level` is negative draw; `energy_step_delta` is per-level change.

Research `energy_tech`: consumption % (`100 − reduction`), not raw “Mineverbrauch −X %” labels.

---

## Rules (GC-000)

- `+` prefix only on delta / step fields
- Absolute rates never prefixed with `+`
- ROI and production delta use **planet context**
- Ship/defense unit detail: `game/ship_detail.py`, `game/defense_detail.py` → `technical` block

---

## Tests

```bash
python -m pytest tests/test_gc823_technical_data.py tests/test_gc823b_technical_data_v2.py tests/test_building_technical_data.py -v
node --check static/main.js
```
