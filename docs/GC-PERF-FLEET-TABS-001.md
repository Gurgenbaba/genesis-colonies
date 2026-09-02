# GC-PERF-FLEET-TABS-001 — Instant Fleet Mode Tabs

## Problem

`/fleet` already server-renders the Send panel plus the embedded Logistics payload. Collect and Distribute are also both present inside the Logistics DOM and are switched by existing client presentation logic.

Despite that, the three top Fleet mode links still performed a new PJAX request to `/fleet` for every mode change. Because Fleet SSR currently builds both the full fleet context and the Logistics context, this made a pure tab switch pay the full server/render cost again.

## Change

`static/js/core/gc.js` now intercepts ordinary left-clicks on `[data-fleet-mode-tab]` during the capture phase and switches the already-rendered panels locally.

- Send ↔ Logistics uses existing `data-fleet-mode-panel` containers.
- Collect ↔ Distribute uses the already-rendered `data-logistics-tab` / `data-logistics-panel` DOM.
- The URL is updated with `history.replaceState`, so reload/deep-link semantics remain intact.
- Modified clicks, missing/invalid embedded payloads and non-ready pages fall back to the existing href/PJAX path.
- On first local entry into Logistics, the existing `GC.modules.logistics` owner is initialized; no parallel Logistics state or poller is introduced.

## Scope

This is a latency/perceived-performance slice only. It does not yet remove the redundant server work where `/fleet` builds both `build_fleet_page_context` and `build_logistics_page_context` for every mode. That backend split is the next performance slice.

## Regression

`tests/test_gc_perf_fleet_tabs_001.py` gates the fast-tab contract and verifies that the Fleet template still contains the required embedded state/panels.
