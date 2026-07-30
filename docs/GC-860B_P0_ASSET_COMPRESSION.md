# GC-860B — P0 Asset Compression

**Status:** DONE (assets + tooling). Template rollout → **GC-860C** (DONE).

## Scope (P0 only)

```text
static/img/background.*
static/img/map.*
static/img/herocards/herocard_*.png + variants
```

**Not in scope (original GC-860B):** buildings, research, shipyard, defense (P1).

**GC-PERF-IMG-001 extended this tool** to also compress:

```text
static/img/herocardsframe/frame.{png,webp}
static/img/expedition/expedition.{png,webp}
static/img/landscapes/*-h.{jpg,webp}
static/img/debris/{asteroid,debris}.{jpg,webp}
```

Card folders use `tools/optimize_images.py` (GC-PERF-IMG-003). Budget contracts: `tests/test_gc_perf_img_budgets.py`.

## Target budgets

| Asset | Target |
|-------|--------|
| `background` / `map` WebP + PNG | **< 500 KB** each |
| `herocard_*-sm.webp` | **30–80 KB** (320px wide) |
| `herocard_*-md.webp` | **80–150 KB** (560px wide) |
| `herocard_*-lg.webp` | ≤280 KB (840px, optional large) |
| `herocard_*.webp` | legacy alias of **-md** (until GC-860C srcset) |
| `herocard_*.png` | fallback resized ≤840px, <500 KB |

## Tooling

```bash
python tools/compress_p0_assets.py --dry-run
python tools/compress_p0_assets.py
python tools/compress_p0_assets.py --report docs/GC-860B_p0_compression_report.md
```

## Variants generated

Per `herocard_XX.png`:

```text
herocard_XX-sm.webp   # 320w
herocard_XX-md.webp   # 560w
herocard_XX-lg.webp   # 840w
herocard_XX.webp      # = md (backward compat)
herocard_XX.png       # compressed fallback
```

## GC-860C (next)

- `overview.html` — `srcset` with sm/md/lg
- `static/style.css` — `map.webp` via `image-set`
- `static/main.js` — responsive herocard URLs from API
- `game/planet_visuals.py` — variant relpath helpers

## Measure after GC-860C

```text
Transferred MB (before/after)
LCP on /overview and /buildings
Image decode time (Chrome Performance)
```

## Tests

```bash
python -m pytest tests/test_gc860b_p0_asset_compression.py -v
```

## Related

- GC-860 — global audit
- GC-859 — buildings hero LCP load attrs
