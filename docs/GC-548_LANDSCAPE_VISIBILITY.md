# GC-548 – Landscape Visibility Regression

**Epic:** Performance / Alpha UX  
**Priorität:** P1 — Regression aus GC-547C  
**Status:** ✅ Implementiert (2026-06-05)

---

## Problem

Planet-Landscapes erschienen nicht beim ersten Seitenaufruf — erst nach Build-Action / `applyGameStateData()`, wenn `gc-perf-idle` kurz entfiel.

## Root Cause

GC-547C setzte `body.gc-perf-idle .gc-bg { display: none }` global. Landscape wird auf `.gc-bg` gerendert (SSR: `gc-has-planet-landscape` + `--planet-landscape`). Im Idle blieb der Layer ausgeblendet, obwohl Body-Klasse und CSS-Variable korrekt waren.

## Fix

### `static/style.css`

- `.gc-bg` nur bei perf-idle **ohne** Landscape ausblenden: `:not(.gc-has-planet-landscape)`
- Mit Landscape: `.gc-bg { display: block }`, Body transparent, `::after`-Overlays weiter aus
- Scanlines / Blur / keine Animation unverändert (GC-547/547B)

### `static/main.js`

- `bootstrapPlanetLandscapeFromBoot()` in `initShellOnce()` — SSR `--planet-landscape` oder `GC.lastState`
- `applyPlanetLandscapeFromState()` entfernt Landscape bei fehlender URL (Planetwechsel)

---

## Akzeptanz

- [x] CSS: Landscape bei `gc-perf-idle` sichtbar
- [x] Boot: `bootstrapPlanetLandscapeFromBoot()` vor `syncPerfBodyClasses`
- [ ] `/overview`, `/buildings` — Landscape sofort sichtbar (Browser)
- [ ] Planetwechsel aktualisiert Landscape
- [ ] Login/Landing GPU-schonend (`.gc-bg` weiter aus)
- [ ] `runningAnims: 0` idle
- [x] `pytest tests/test_static_live_updates.py -v` grün

---

## Changed Files

- `static/style.css`
- `static/main.js`
- `tests/test_static_live_updates.py`
- `docs/GC-548_LANDSCAPE_VISIBILITY.md`
- `docs/GC-547_GPU_PERFORMANCE_AUDIT.md`
