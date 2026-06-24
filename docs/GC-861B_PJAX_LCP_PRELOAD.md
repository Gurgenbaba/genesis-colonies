# GC-861B — PJAX LCP Preload + Static Image Cache

**Status:** DONE  
**Follow-up:** [GC-861C](GC-861C) Hero-Macro-Rollout Research/Shipyard/Defense

## Root Cause

Hard reload injects `<link rel="preload">` via `templates/buildings.html` `extra_head`, but PJAX swaps only `#main-content`. The LCP hero image is discovered late → dark hero slot visible before paint (Resource Load Delay).

Unversioned raster assets under `/static/` had no explicit `Cache-Control` → repeat visits depend on browser heuristics (“oft, nicht immer”).

## Fix

### PJAX (`static/main.js`)

After PJAX HTML parse, **before** `main.innerHTML` swap:

1. Find `[data-gc-lcp-hero="1"]` in fetched `#main-content`
2. Read `src` (WebP primary from GC-861)
3. Upsert single `<link id="gc-lcp-hero-preload" rel="preload" as="image">` in `<head>`
4. Remove link when target page has no LCP hero (no duplicates)

### Static cache (`app.py`)

Raster files under `/static/` (`.webp`, `.png`, `.jpg`, `.jpeg`, `.gif`, `.svg`):

```http
Cache-Control: public, max-age=604800
```

7 days — conservative until image URLs get query-version busting (`?v={{ GC_ASSET_VERSION }}`). Then `immutable` + 1y is safe.

**Not cached long:** JS/CSS/HTML/API routes.

## Changed Files

- `static/main.js` — `syncLcpHeroPreloadFromPjaxDoc`, PJAX hook
- `app.py` — `apply_static_image_cache_headers`
- `tests/test_gc861b_pjax_lcp_preload.py`
- `docs/GC-861B_PJAX_LCP_PRELOAD.md`

## Tests

```bash
python -m pytest tests/test_gc861b_pjax_lcp_preload.py tests/test_gc861_building_lcp_stability.py -v
```

## Manual QA

1. Hard reload → `/overview`
2. PJAX → `/buildings?tab=resources`
3. DevTools → Elements: `<head>` contains `#gc-lcp-hero-preload` with `metal_mine.webp`
4. Network → Img: hero WebP starts before or with DOM swap; no duplicate preload links
5. Repeat visit → static image served from disk cache (`from disk cache`)

## Ergebnis

| Item | Verdict |
|------|---------|
| PJAX preload gap | **fixed** |
| Static image cache | **7d public** |
| SSR refactor | none |
| Gameplay | none |

## Related

- GC-861 — Buildings LCP priority / discovery
- GC-861C — Hero macro rollout (Research/Shipyard/Defense)
