# GC-PG-QUEUE-LOCK-001 — Queue worker skips contended planets

## Problem

The dedicated PostgreSQL queue worker discovers due planet-scoped work with a read-only scan. Between discovery and the write transaction, an HTTP request or another writer can already own the same planet scope. The worker then waited until PostgreSQL `lock_timeout`, producing repeated errors such as `queue_engine shipyard finish failed ... cancelling statement due to lock timeout`.

## Contract

- Interactive/request mutations keep the normal blocking `lock_planet_for_update()` semantics.
- Background queue ticks claim a due planet with `FOR UPDATE SKIP LOCKED` before any planet queue family is finished.
- A contended planet is **not an error** and no queue state is modified for that scope.
- The due row remains due and is retried by the next worker heartbeat.
- SQLite behavior is unchanged (`BEGIN IMMEDIATE` remains the writer serializer).
- Account-scoped research is unchanged.

## Observability

`finish_due_work()` reports `skipped_locked_planets`; `run_tick()` merges the list and logs `locked_skips=<n>`.

## Regression gate

`tests/test_gc_perf_queue_worker_001.py` verifies that queue-only planet calls enable skip-locked claiming and that the PostgreSQL helper emits `FOR UPDATE SKIP LOCKED` and returns immediately when no row can be claimed.
