# GC-PERF-SHIPYARD-CATALOG-001 — Shared Shipyard Catalog Snapshot

## Problem

The Shipyard API built Buildable and Locked catalogs as separate scans. Inside those scans, per-ship helpers could independently reload or resolve Buildings, Research, combat/effect context, Forge rank, Shipyard time speed, inventory, unlock requirements and unit costs.

That made one `/shipyard` page payload scale with the number of ship definitions instead of with the number of canonical state sources.

## Change

`_build_shipyard_catalogs_shared()` now prepares one server-side catalog snapshot per payload:

- planet Buildings and effective Shipyard level;
- player Research;
- current resources;
- current planet ship inventory;
- queue-full state;
- technical/effect context;
- Stellar Forge rank;
- effective Shipyard time-speed multiplier.

A single ordered loop over `ACTIVE_SHIP_KEYS` then creates each catalog entry and partitions it into Buildable or Locked.

The public helpers keep compatible fallbacks. `ship_unlocked()`, `_ship_catalog_entry()`, `max_build_amount_for_planet()` and `_effective_build_seconds()` can still resolve their own inputs when called outside the shared catalog path.

`build_shipyard_api_payload()` consumes the one shared snapshot and only adds planet metadata plus the existing queue payload afterward.

## Gameplay invariants

This changes data reuse, not gameplay formulas or authority:

- unlock requirements stay owned by `ship_requirements`;
- unit costs stay owned by the canonical Shipyard cost path;
- combat stats still use `technical_data`;
- Shipyard time-speed still uses universe speed and the directive/effect resolver;
- Forge rank and batch capacity formulas are unchanged;
- server remains the only gameplay authority.

No cache-as-truth, second state store, new poller or client-side calculation was added.

## Regression gates

`tests/test_gc_perf_shipyard_catalog_001.py` enforces one shared snapshot and one ship loop while preserving fallback-capable helpers.

The normal Smoke gate also runs `tests/test_shipyard.py::test_buildable_ships_by_level`, exercising the real DB-backed unlock transition used by the catalog.
