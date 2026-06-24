# GC-860 — Global Image Asset Optimization

**Phase:** Audit (GC-860) → Batch conversion (GC-860B) → Template rollout (GC-860C)

**Not GIF.** Target delivery:

```text
WebP primary
PNG/JPG fallback
responsive sizes where overserved
```

## Problem

GC-854/859 fixed Buildings SSR and WebP LCP for heroes, but project-wide many templates still reference **PNG/JPG primaries** while WebP siblings exist. Card heroes are **512×358** assets rendered at **~210×118** (overserving).

Ferdi observation: 322 KB PNG displayed at 206×95 → classic LCP/weight issue.

## Tooling

```bash
python tools/audit_image_assets.py
python tools/audit_image_assets.py --min-kb 100
python tools/audit_image_assets.py --json > docs/GC-860_image_audit_report.json
python tools/audit_image_assets.py --markdown docs/GC-860_image_audit_report.md
```

Output:

```text
file | bytes | width x height | used_in | rendered_size | recommendation
```

Related:

- `tools/audit_building_hero_images.py` — buildings-only (GC-859)
- `tools/audit_assets.py` — GC-555 size-only legacy
- `tools/optimize_images.py` — GC-549 resize/compress (GC-860B candidate)

## Audit rules

| Flag | Threshold | Action |
|------|-----------|--------|
| Heavy PNG/JPG | ≥250 KB | WebP primary + GC-860B compress |
| Overserved card | w>360 in buildings/ships/defense/research | resize ~320×180 |
| Missing WebP | PNG without sibling | generate in GC-860B |
| Above-fold | first 1–3 cards | eager + fetchpriority=high |
| Below-fold | rest | lazy + fetchpriority=low |
| Icons/transparency | small badges, UI | do not blind-convert; test alpha |

## Scope (GC-860B/C — not this ticket)

1. Batch WebP generation (`tools/optimize_images.py` / `convert_webp.py`)
2. Templates: shipyard, defense, research → WebP primary (buildings done GC-859)
3. Responsive `srcset` where still overserved after compress
4. **No** gameplay, SSR, queue changes

## Target values (card heroes)

| Display | Asset target |
|---------|----------------|
| ~210×118 CSS | **320×180 WebP, 30–80 KB** |
| Not | 512×358 PNG 300+ KB |

## Classification

| Verdict | Meaning |
|---------|---------|
| OK | WebP ≤80 KB card / small icon |
| WEBP_PRIMARY_GAP | sibling exists, template still PNG |
| OVERSERVED | pixels >> render box |
| GC-860B | needs (re)generation |
| GC-860C | template/CSS delivery fix |

## Tests

```bash
python -m pytest tests/test_gc860_image_asset_audit.py -v
```

## Related tickets

- GC-555 — first global asset audit
- GC-859 — building hero LCP (committed)
- GC-860B — compress/generate assets
- GC-860C — template rollout project-wide
