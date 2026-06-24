# GC-859 — Building Hero Image LCP Audit

**Status:** DONE (audit + safe load-path fix; no new assets)

## Root Cause

Chrome LCP element `img.gc-bld-card-hero-img` (~5,53 s) while SSR is ~600 ms warm (GC-854) because:

1. **GC-854** switched heroes from `render_raster_picture` (WebP) to plain **PNG** `<img>` (~**323 KB** vs WebP ~**38 KB** per mine).
2. **Active queue** heroes were always `loading="lazy"` + `fetchpriority="low"` even above the fold.
3. Card renders at ~320×180 CSS but assets are **512×358** — acceptable; **format/bytes** dominate latency.

LCP measures **largest painted image**, not TTFB.

## Image Audit (summary)

Run: `python tools/audit_building_hero_images.py`

| Building | WebP bytes | PNG bytes | WxH | Above-fold (resources tab) |
|----------|-----------|-----------|-----|----------------------------|
| metal_mine | 38 416 | 322 254 | 512×358 | yes (LCP #1) |
| crystal_mine | 57 778 | 430 858 | 512×358 | yes |
| solar_plant | 51 078 | 403 013 | 512×358 | yes |
| fuel_cell_plant | 56 886 | 418 782 | 512×358 | row 4 → lazy |
| research_lab | 39 460 | 296 996 | 512×358 | — |
| default | 30 724 | 300 661 | 512×358 | fallback |

**Flags:** 19 PNG files **> 300 KB**; all have WebP siblings **< 70 KB**. No PNG > 1000 px width.

Full JSON: `python tools/audit_building_hero_images.py`

## Fix (GC-859, no gameplay)

`templates/buildings.html`:

| Row | `loading` | `fetchpriority` | `src` |
|-----|-----------|-----------------|-------|
| 1st card | `eager` | `high` | `.webp` → PNG `onerror` |
| 2nd–3rd | `eager` | (default) | `.webp` → PNG `onerror` |
| 4th+ | `lazy` | `low` | `.webp` → PNG `onerror` |

Active-queue dual heroes use the **same** load tier (was always lazy/low).

No `<picture>` wrapper (keeps GC-854 template lean); single `<img>` + WebP primary.

## Changed Files

- `templates/buildings.html` — WebP primary, tiered load attrs, active-queue fix
- `tools/audit_building_hero_images.py` — asset inventory
- `tests/test_gc859_building_hero_lcp.py` — HTML contract tests
- `docs/GC-859_BUILDING_HERO_LCP_AUDIT.md` — this doc

## Tests

```bash
python -m pytest tests/test_gc859_building_hero_lcp.py tests/test_gc854_buildings_ssr_optimization.py -v
```

## LCP Before / After

| Metric | Before (reported) | Expected after |
|--------|-------------------|----------------|
| LCP element | `img.gc-bld-card-hero-img` | same element |
| LCP time | ~5,53 s | **measure** (target: WebP + eager high → sub-2 s on typical link) |
| First image bytes | ~322 KB PNG | ~38 KB WebP |
| SSR | ~600 ms warm | unchanged |

**Manual QA:** Hard reload `/buildings?tab=resources` → Performance panel LCP + Network Img filter.

## Ergebnis

| Item | Verdict |
|------|---------|
| LCP bottleneck | **Client image pipeline** (not SSR) |
| WebP assets exist | yes — use them |
| Above-fold lazy bug | **fixed** |
| Further compression | **GC-859B** if WebP still too heavy |
| Preload `<link>` | not needed yet; revisit if LCP still high |

## Related

- GC-854 — SSR optimization (removed WebP picture → LCP regression)
- GC-858 — build-time balance (orthogonal)
