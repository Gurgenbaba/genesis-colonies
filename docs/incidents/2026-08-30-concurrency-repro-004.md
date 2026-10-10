# GC-PROD-INFINITY-LOAD-REPRO-004 — Production Topology + State Replay

Date: 2026-08-30  
Branch: `fix/prod-infinity-load-concurrency-repro`  
Harness: **Docker** `python:3.12-slim` + **Gunicorn `-k gevent -w 1`** + optional maintenance sidecar  
No hotfix / no Railway / no main / #125 untouched.

## Context shift (from REPRO-003)

REPRO-003 showed A/B/C penalties ≈ equal → **STATE-012/013 not implicated**.

REPRO-004 asks instead: which **production topology + state + request-side writes** recreate multi-route stalls?

## PRODUCTION TOPOLOGY

**verified: yes**

| Check | Result |
|-------|--------|
| Gunicorn running | yes |
| `worker_class=gevent` | yes |
| workers=1 | yes |
| Maintenance sidecar separate process | yes |
| Embedded cron off (`disabled_sidecar_owns_bag`) | yes |

WSL note: only `docker-desktop` distro was present (no full Linux user distro). Docker Desktop was used as the production-topology harness.

## CONTROL (no sidecar)

4 clients · 161 MB seed · 60s · Gunicorn gevent w=1 · auth_ok=1.0

| Metric | `/api/game-state` |
|--------|-------------------|
| p50 | **5597 ms** |
| p95 / p99 / max | **10156 ms** |
| slow5 | **21** |

Already multi-second under calibrated client count — unlike Flask-threaded REPRO-003 (~300 ms p50). **Topology matters.**

## SIDECAR PENALTY

With real `run_maintenance_worker.py` sidecar:

| Metric | Value |
|--------|-------|
| Maint gs p95 | 10529 ms |
| Penalty p95 | **+373 ms** |
| Penalty p99 | ~+373 ms |
| slow5 | 19 |

Sidecar adds modest penalty; **baseline gevent worker is already the stall.**

## WORST STATE

| State | gs p50 / p95 | Notes |
|-------|--------------|-------|
| S0 NORMALIZED | 4667 / 8230 | Already bad |
| S5 FLEET+QUEUES | 7087 / 11053 | Worse |
| **S7 WORST_PLAUSIBLE** | **6339 / 11247** | Worst tested |

**WORST_STATE:** `S7_WORST_PLAUSIBLE`  
**WORST_ROUTE:** `/api/game-state` (cascade also hits `/messages`, `/world-boss`, `/galaxy`, `/api/chat/bootstrap`)

## HTTP WRITE PATH

Server perf log aggregation often lost on container stop (`write_paths.n=0`).

Code-level dominant candidates (unchanged):

1. `player_fleet_is_dirty` → `process_fleet_tick` on poll  
2. `player_has_due_queue_work` → `finish_player_due_work` / `finish_due_work_once`  
3. `record_poll_queue_finish` + resource persist `BEGIN IMMEDIATE`

## THUNDERING HERD

**yes** — S5 + 8 clients: gs p95 ≈ **13.4 s**, slow5=36. Multiple authenticated players with due fleet/queue work pile onto the same 1-worker gevent process.

## GEVENT_WORKER_BLOCKED_BY_SQLITE_WAIT

**yes** (measured, not guessed)

During S5 load (10 clients + sidecar):

| Probe | Result |
|-------|--------|
| `/api/game-state` p95 | **22.6 s** |
| `/healthz` p50 / p95 / max | **30.0 / 30.0 / 30.0 s** (timeouts) |

`/healthz` does not need a writer. When it hangs in lockstep with game routes, the **entire gevent worker** is effectively frozen during blocking `sqlite3` waits.

This matches the incident shape: container alive, proxy may still answer some paths, dynamic Flask routes hang, 499 after many seconds, CPU need not spike.

## 1 WORKER vs 2 WORKERS

Same S5 seed, sidecar on, 4 clients, 60s:

| Workers | gs p50 / p95 | slow5 |
|---------|--------------|-------|
| 1 | 7086 / 10742 | 20 |
| 2 | 4010 / 5484 | 20 |

2 workers **improves** latency (~half p95) but **does not eliminate** multi-second stalls / slow5. Not a claimed fix — tradeoff only.

## DOUBLE MAINTENANCE OWNER

**possible under misconfiguration only**

Owner matrix (`artifacts/concurrency_repro/repro004/owner_matrix.json`):

- Production intended: sidecar ON, embedded OFF  
- Leader lock (`.gc_embedded_cron.lock`) prevents sidecar + embedded double bag  
- HTTP `/api/internal/cron/*` and request safety nets remain additional write owners

## RESTART CLEARS STALL

**no**

Same DB snapshot:

| | gs p95 | slow5 |
|--|--------|-------|
| Before web restart | 6019 | 13 |
| After web restart | 6901 | 11 |

Restart alone does **not** clear the stall class in this harness.

## Gates

| Gate | Result |
|------|--------|
| PRODUCTION TOPOLOGY | **verified yes** |
| SYSTEM FAILURE MODE | **yes** |
| HISTORICAL INCIDENT | **reproduced no** (still no proof this == 2026-08-29) |
| ROOT CAUSE | **under investigation** |

## NEXT MINIMAL FIX (proposal only — do not implement)

1. Treat **gevent + blocking sqlite3** as primary hypothesis for multi-route freeze.  
2. Next experiment: same load with `GUNICORN_WORKER_CLASS=sync` (or `gthread`) vs gevent — isolate worker-class effect.  
3. Instrument HTTP safety nets with durable request_id → write path logs (persist before container stop).  
4. Keep STATE-012/013 off the critical path until new evidence.  
5. Still no Railway / no hotfix / no #125 merge.

## Scripts

- `scripts/prod_infinity_load_repro004.py`
- `scripts/_repro004_topology_entry.sh`
- `scripts/_repro004_prepare_state.py`
- `scripts/_repro004_owner_matrix.py`
- `scripts/_repro004_common.py`

Artifacts: `artifacts/concurrency_repro/repro004/` (gitignored).

## Follow-up

**REPRO-005** confirmed the mechanism: `docs/incidents/2026-08-30-concurrency-repro-005.md`.
