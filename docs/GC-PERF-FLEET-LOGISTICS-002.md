# GC-PERF-FLEET-LOGISTICS-002 — Read-only Logistics SSR

## Problem

`/fleet` builds the embedded Logistics context even while the Send panel is visible so Collect/Distribute can switch instantly. The Logistics page-context loop computes current resource stocks for every owned colony with `update_planet_resources(...)`.

For a GET/SSR page render those calculations were also persisted. That means opening Fleet could cause resource writes across several colonies before the user performed any Logistics action, increasing PostgreSQL work and contention on an already heavy page.

## Change

The resource refresh inside `build_logistics_page_context()` now uses `persist=False`.

- live production is still calculated for the displayed colony stock;
- the SSR GET path does not write those calculated balances merely for presentation;
- Collect/Distribute preview and mutation paths are unchanged;
- action-time validation remains authoritative and persists through the existing transaction owners;
- the embedded Logistics payload remains available, so the instant Fleet mode tabs from GC-PERF-FLEET-TABS-001 stay instant.

## Architecture

No new state, poller or calculation engine. This only makes a read-only presentation path actually read-only while preserving the canonical resource formula and Fleet/Logistics owners.

## Regression

`tests/test_gc_perf_fleet_logistics_readonly_002.py` scopes `persist=False` to `build_logistics_page_context()` and asserts that mutating Fleet resource paths retain their existing persistence behavior.
