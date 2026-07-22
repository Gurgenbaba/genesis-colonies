# GC-548 – Landscape Visibility Regression

**Epic:** Performance / Alpha UX  
**Priorität:** P1 — Regression aus GC-547C  
**Status:** ✅ Implementiert (2026-06-05) · **PJAX-Preserve** ✅ (2026-07-22)

---

## Problem

Planet-Landscapes erschienen nicht beim ersten Seitenaufruf — erst nach Build-Action / `applyGameStateData()`, wenn `gc-perf-idle` kurz entfiel.

**Folgeregression (PJAX):** Nach Light-PJAX / Soft-Reload verschwand die Shell-Landschaft dauerhaft. Lightweight-Fragment-SSR liefert kein `--planet-landscape`; `applyPjaxPayload` interpretierte das als Clear. Mit `skipGameState` / Diet-`unchanged` kam kein Restore — und `gc-perf-idle:not(.gc-has-planet-landscape)` blendete `.gc-bg` aus.

## Root Cause

GC-547C setzte `body.gc-perf-idle .gc-bg { display: none }` global. Landscape wird auf `.gc-bg` gerendert (SSR: `gc-has-planet-landscape` + `--planet-landscape`). Im Idle blieb der Layer ausgeblendet, obwohl Body-Klasse und CSS-Variable korrekt waren.

PJAX: leere Payload-Landscape ≠ „kein Planet“ — Shell-Contract (GC-PERF-PJAX-CTX-SHELL-001): Landscape gehört zur Shell und bleibt im DOM.

## Fix

### `static/style.css`

- `.gc-bg` nur bei perf-idle **ohne** Landscape ausblenden: `:not(.gc-has-planet-landscape)`
- Mit Landscape: `.gc-bg { display: block }`, Body transparent, `::after`-Overlays weiter aus
- Scanlines / Blur / keine Animation unverändert (GC-547/547B)

### `static/main.js`

- `bootstrapPlanetLandscapeFromBoot()` in `initShellOnce()` — SSR `--planet-landscape` oder `GC.lastState`
- `applyPlanetLandscapeFromState()` entfernt Landscape nur bei explizit leerer `landscape_url` im State
- `applyPjaxPayload`: leere PJAX-Landscape → **nicht clearen**; `ensurePlanetLandscapeAfterSoftNav()` (lastState / boot)
- Soft-Reload PE + Planet-Switch: Guard `ensurePlanetLandscapeAfterSoftNav()` nach PJAX

---

## Akzeptanz

- [x] CSS: Landscape bei `gc-perf-idle` sichtbar
- [x] Boot: `bootstrapPlanetLandscapeFromBoot()` vor `syncPerfBodyClasses`
- [x] PJAX ohne Landscape-SSR clear’t Shell nicht
- [ ] `/overview`, `/buildings` — Landscape sofort sichtbar (Browser)
- [ ] Planetwechsel aktualisiert Landscape
- [ ] Login/Landing GPU-schonend (`.gc-bg` weiter aus)
- [ ] `runningAnims: 0` idle
- [x] `pytest tests/test_static_live_updates.py -k landscape -q` grün

---

## Changed Files

- `static/style.css`
- `static/main.js`
- `tests/test_static_live_updates.py`
- `docs/GC-548_LANDSCAPE_VISIBILITY.md`
- `docs/GC-547_GPU_PERFORMANCE_AUDIT.md`
