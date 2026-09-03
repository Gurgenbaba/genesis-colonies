# GC-PERF-FLEET-SHARED-004 — Shared Fleet Request Context

## Problem

`/fleet` renders both the Send panel and the embedded Logistics panel so switching between Send / Collect / Distribute can stay instant. Before this slice, both page-context builders repeated request-local work:

- active-planet Shipyard finish;
- `process_fleet_tick()`;
- owned-planet enumeration;
- Fleet slot status;
- Fleet mission locks.

The second pass did not create new authority or fresher gameplay state; it merely recomputed state that had just been produced earlier in the same SSR request.

## Change

The `/fleet` route now loads the owned planet rows once and passes them into both builders.

`build_fleet_page_context()` remains the canonical maintenance owner for the combined Fleet SSR. Its already-calculated `fleet_slots` and `mission_locks` are handed to `build_logistics_page_context()` together with `maintenance_prepared=True`.

`build_logistics_page_context()` keeps backwards-compatible defaults:

- without explicit shared inputs it still runs Shipyard/Fleet maintenance itself;
- without `planet_rows` it still loads the player's planets itself;
- without shared slots/locks it still reads them itself.

That preserves standalone/tests/other callers while removing duplicate work only when the two panels are built together by `/fleet`.

## Architecture

No cache, second state store, new poller or client-side gameplay authority. This is request-local reuse of canonical server results only.

## Regression

`tests/test_gc_perf_fleet_shared_request_004.py` gates:

- one planet-list query in the `/fleet` route;
- both builders consume the same planet rows;
- Logistics explicitly receives the Send maintenance result;
- standalone Logistics keeps its historical maintenance fallback;
- Send remains the maintenance owner for the combined request.
