# GC-861D — Global Card Hero Rollout

**Status:** DONE  
**Depends on:** GC-861, GC-861B, GC-861C

## Root Cause

Card hero LCP pattern was canonical on Buildings/Research/Shipyard/Defense only. Other pages with visible hero/card art still used PNG-primary, missing `data-gc-lcp-hero`, or lacked SSR preload — PJAX preload (861B) could not fire.

## Audit

| Seite | Bildtyp | Vorher | Umstellen? | Aktion |
| ----- | ------- | ------ | ---------- | ------ |
| Buildings | Card hero 16:9 | GC-861C ✅ | — | — |
| Research | Card hero + queue stack | GC-861C ✅ | — | — |
| Shipyard | Card hero | GC-861C ✅ | — | — |
| Defense | Card hero | GC-861C ✅ | — | — |
| **Overview** | Planet herocard (picture) | WebP srcset, 1× high, kein LCP mark | **Ja** | `data-gc-lcp-hero`, SSR preload, WebP hint |
| **Inventory** | Container loot cards | PNG lazy, kein LCP | **Ja** | `render_card_hero_img`, first high + LCP |
| **Fleet** | Ship pick thumbs 96×96 | picture lazy all | **Ja** | First ship high + LCP, SSR preload |
| Planet Evolution | Text/CSS hero | keine Hero-Bilder | Nein | — |
| Galaxy | CSS map background | keine `<img>` heroes | Nein | — |
| Logistics | — | keine Card heroes | Nein | — |
| Auction House | Table thumbs ~48px | lazy | Nein | kleine Icons |
| Vote Center | Reward thumbs | lazy | Nein | kleine Icons |
| Records | Prog icons | lazy | Nein | kleine Icons |
| Ranking | JS avatars | lazy | Nein | kleine Icons |
| Playercard | Avatar | lazy external | Nein | kleine Icons |
| Techtree | Tech icons | lazy | Nein | kleine Icons |

## Fix

### Shared macro (`partials/card_hero_img_macros.html`)

- `render_card_hero_img` — single WebP-primary hero (Inventory-style)
- `data-gc-lcp-webp-href` on all LCP heroes (stack + flat)

### PJAX (`static/main.js`)

`resolveLcpHeroImageUrl` prefers `data-gc-lcp-webp-href`, then `<picture><source webp>`, then PNG→WebP rewrite.

### Pages updated

- `templates/overview.html` — LCP mark + SSR preload
- `templates/inventory.html` — macro + tiered load + preload
- `templates/fleet.html` — first ship LCP + preload + `render_hero_img_attrs`

## Changed Files

- `templates/partials/card_hero_img_macros.html`
- `templates/overview.html`
- `templates/inventory.html`
- `templates/fleet.html`
- `static/main.js`
- `tests/test_gc861d_global_card_hero_rollout.py`
- `docs/GC-861D_GLOBAL_CARD_HERO_ROLLOUT.md`

## Tests

```bash
python -m pytest tests/test_gc861d_global_card_hero_rollout.py tests/test_gc861c_hero_macro_rollout.py tests/test_gc861b_pjax_lcp_preload.py tests/test_gc861_building_lcp_stability.py -q
```

## Ergebnis

| Kriterium | Status |
| --------- | ------ |
| Audit doc | ✅ |
| PNG-primary Card heroes (WebP exists) | ✅ auf LCP-Seiten |
| Multiple `fetchpriority="high"` pro Seite | ✅ vermieden |
| PJAX preload via `data-gc-lcp-hero` | ✅ Overview/Inventory/Fleet + 861C |
| Buildings/Research/Shipyard/Defense | ✅ unverändert grün |
