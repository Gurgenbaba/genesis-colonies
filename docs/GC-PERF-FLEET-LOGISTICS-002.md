# GC-PERF-FLEET-LOGISTICS-002/003 — Lean Logistics SSR

## Problem

`/fleet` builds the embedded Logistics context even while the Send panel is visible so Collect/Distribute can switch instantly. That context had two avoidable costs:

1. current resource stocks for every owned colony were calculated with `update_planet_resources(...)` **and persisted**, even though this is only a GET/SSR presentation path;
2. ship inventories were loaded with `get_planet_ships()` once per colony and then again for the active hub, producing an N+1-style hangar read pattern as colony count grows.

## Changes

### GC-PERF-FLEET-LOGISTICS-002 — read-only resource refresh

The resource refresh inside `build_logistics_page_context()` now uses `persist=False`.

- live production is still calculated for the displayed colony stock;
- the SSR GET path does not write calculated balances merely for presentation;
- Collect/Distribute preview and mutation paths are unchanged;
- action-time validation remains authoritative and persists through the existing transaction owners.

### GC-PERF-FLEET-LOGISTICS-003 — batched hangar read

The same page context now reads `planet_ships` once for the player and groups the rows by `planet_id` in memory.

- one player-scoped query replaces one `get_planet_ships()` call per colony plus the extra hub lookup;
- per-colony cargo filtering still consumes the exact same ship-count maps;
- the returned active-hub `ships` field comes from the same batch;
- no Fleet mutation or ship deduction path is changed.

The embedded Logistics payload remains available, so the instant Fleet mode tabs from GC-PERF-FLEET-TABS-001 stay instant without trading that UX improvement for avoidable PostgreSQL work.

## Architecture

No new state, cache-as-truth, poller or calculation engine. Resource production remains owned by the canonical resource path, and ship inventory remains backed by `planet_ships`. This slice only makes a read-only presentation path read-only and batches repeated reads of the same canonical table.

## Regression

`tests/test_gc_perf_fleet_logistics_readonly_002.py` now gates both optimizations:

- `persist=False` remains scoped to `build_logistics_page_context()`;
- the page context must use one `planet_ships` batch and may not reintroduce per-colony/hub `get_planet_ships()` calls;
- mutating Fleet resource paths retain their existing persistence behavior.
