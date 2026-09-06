# GC-PERF-FLEET-SSR-005 — Mode-Specific Fleet SSR

**Status:** ✅ Shipped

## Problem

`/fleet` used to build both `build_fleet_page_context` and
`build_logistics_page_context` for every request, and `fleet.html` emitted
both heavy DOM trees even though only one top-level mode was visible.

That meant a direct Send, Collect, or Distribute navigation paid for hidden
server work and hidden response bytes.

## Contract

1. Resolve `mode=send|collect|distribute` before heavy context construction.
2. **Send:** build only `build_fleet_page_context`.
3. **Collect/Distribute:** build only `build_logistics_page_context`.
4. Logistics SSR carries a tiny `fleet_ctx` shell marked ready so `initFleet`
   does not immediately fetch the hidden Send catalog.
5. `fleet.html` emits only the requested top-level heavy panel.
6. Collect ↔ Distribute can still switch locally because both are owned by the
   same Logistics payload.
7. Send ↔ Logistics falls back to the existing PJAX href whenever the target
   top-level panel was intentionally not rendered.
8. One `/fleet` route, Planet Scope, Fleet owner, Logistics owner, and server
   authority remain unchanged.

## Regression

- `tests/test_gc_perf_fleet_tabs_001.py`
- `tests/test_gc_perf_fleet_shared_request_004.py`
- Genesis Sentinel / standard CI
