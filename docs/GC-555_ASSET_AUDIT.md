# GC-555 — Global Asset Audit & Image Loading Optimization

Audit date: 2026-06-11. Machine-readable report: [GC-555_asset_report.json](GC-555_asset_report.json).

## Summary

| Metric | Value |
|--------|-------|
| Raster assets scanned | 101 |
| Warning (≥ 250 KB) | 58 |
| Critical (≥ 500 KB) | 4 |
| WebP siblings generated | 101 |
| Estimated transfer saved (WebP vs PNG/JPG) | ~28 MB |

Thresholds: **warning ≥ 250 KB**, **critical ≥ 500 KB**.

## Top 10 largest assets (source)

| KB | Category | Path |
|----|----------|------|
| 2587 | root | `static/img/background.png` |
| 567 | vote | `static/img/vote/GameToor.png` |
| 536 | vote | `static/img/vote/GTop100.png` |
| 518 | vote | `static/img/vote/Arena-Top100.png` |
| 481 | vote | `static/img/vote/TopG.png` |
| 453 | lootboxes | `static/img/lootboxes/Event_Container.png` |
| 449 | lootboxes | `static/img/lootboxes/Research_Cache.png` |
| 443 | buildings | `static/img/buildings/fuel_cell_storage.png` |
| 429 | buildings | `static/img/buildings/crystal_storage.png` |
| 427 | lootboxes | `static/img/lootboxes/Military_Cache.png` |

## Top 10 optimization wins (WebP transfer saved)

| Saved KB | PNG/JPG → WebP | Path |
|----------|----------------|------|
| 2331 | 2587 → 256 | `static/img/background.png` |
| 491 | 567 → 76 | `static/img/vote/GameToor.png` |
| 466 | 536 → 70 | `static/img/vote/GTop100.png` |
| 454 | 518 → 65 | `static/img/vote/Arena-Top100.png` |
| 428 | 481 → 53 | `static/img/vote/TopG.png` |
| 376 | 443 → 67 | `static/img/buildings/fuel_cell_storage.png` |
| 368 | 429 → 61 | `static/img/buildings/crystal_storage.png` |
| 364 | 421 → 57 | `static/img/buildings/crystal_mine.png` |
| 364 | 417 → 53 | `static/img/buildings/metal_storage.png` |
| 356 | 449 → 93 | `static/img/lootboxes/Research_Cache.png` |

## Implemented (GC-555)

### Tooling

- `tools/audit_assets.py` — size report JSON
- `tools/audit_assets_webp.py` — WebP savings enrichment
- `tools/convert_webp.py` — batch WebP generation (quality 82, resize if ≥ 400 KB)

### WebP delivery

- Jinja filter `webp_static` (`app.py`)
- `render_raster_picture` macro — `<picture>` WebP + PNG/JPG fallback
- Planet landscapes: `--planet-landscape-webp` CSS var + `image-set` on `.gc-bg`
- Landing/login/register: `background.webp` via `image-set` in CSS
- Vote Center: banner as CSS background (`--vote-banner` / `--vote-banner-webp`), dark gradient overlay

### Templates updated

- `templates/buildings.html`, `research.html` — hero cards via `render_raster_picture`
- `templates/shipyard.html`, `defense.html` — ship/defense hero cards
- `templates/vote_center.html` — provider banner backgrounds
- `templates/base.html` — landscape WebP CSS variable on SSR

### Backend / client

- `game/planet_visuals.py` — `raster_webp_relpath()`, `landscape_webp_relpath()`
- `app.py` — `landscape_webp_url` in game-state + shell context
- `static/main.js` — `landscapeWebpUrlFromRaster()`, PJAX copies `--planet-landscape-webp`

### CSS

- Hero `<picture>` positioning
- Vote Center card banner backgrounds + stronger overlay
- No extra fullscreen backgrounds per page (landscape remains single `.gc-bg` layer)

## Manual QA checklist

- [ ] `/vote-center` — banners readable, vote buttons clear
- [ ] `/buildings`, `/research` — hero WebP loads, queue progress overlay intact
- [ ] `/shipyard`, `/defense` — card icons lazy-load
- [ ] `/overview` — one landscape only, WebP in Network tab
- [ ] `/empire`, `/planet-evolution` — no regression
- [ ] DevTools Network — WebP served where supported
- [ ] `GC.debugPerf()` unchanged

## Regenerate report

```bash
python tools/audit_assets.py
python tools/convert_webp.py
python tools/audit_assets_webp.py
```
