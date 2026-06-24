# GC-861C — Hero Macro Rollout (Research / Shipyard / Defense)

**Status:** DONE  
**Depends on:** GC-861 (Buildings), GC-861B (PJAX preload)

## Root Cause

Research used `render_raster_picture` with duplicate `fetchpriority="high"` on active-queue muted + color layers. Shipyard/Defense used PNG-primary `<picture>` with cards 1–3 eager — inconsistent with Buildings GC-861 contract and no `data-gc-lcp-hero` for PJAX preload.

## Fix

Shared partial `templates/partials/card_hero_img_macros.html`:

- WebP `src` + PNG `onerror` fallback
- One `fetchpriority="high"` per card (primary only; secondary `low` when active queue)
- `data-gc-lcp-hero="1"` on first card per page
- `<link rel="preload">` in `extra_head` for Research, Shipyard, Defense

| Page | Card 1 | Card 2+ |
|------|--------|---------|
| Research | high + LCP mark | lazy + low |
| Shipyard buildable | high + LCP mark | lazy + low |
| Defense buildable | high + LCP mark | lazy + low |
| Locked cards | lazy + low | — |

Buildings imports the same partial (no duplicate macro).

## Changed Files

- `templates/partials/card_hero_img_macros.html` — new canonical macro
- `templates/buildings.html` — import partial
- `templates/research.html`
- `templates/shipyard.html`
- `templates/defense.html`
- `tests/test_gc861c_hero_macro_rollout.py`
- `tests/test_gc861_building_lcp_stability.py` — partial path update
- `docs/GC-861C_HERO_MACRO_ROLLOUT.md`

## Tests

```bash
python -m pytest tests/test_gc861c_hero_macro_rollout.py tests/test_gc861_building_lcp_stability.py tests/test_gc861b_pjax_lcp_preload.py -v
```

## Ergebnis

| Page | PJAX preload | WebP primary | Single high priority |
|------|--------------|--------------|----------------------|
| Buildings | ✅ (861B) | ✅ | ✅ |
| Research | ✅ | ✅ | ✅ |
| Shipyard | ✅ | ✅ | ✅ |
| Defense | ✅ | ✅ | ✅ |

## Related

- GC-860B — asset compression if heroes still heavy after this
- GC-861B — PJAX `<head>` preload injection
