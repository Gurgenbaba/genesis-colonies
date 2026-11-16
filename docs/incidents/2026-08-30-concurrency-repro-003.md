# GC-PROD-INFINITY-LOAD-REPRO-003 — Differential Concurrency

Date: 2026-08-30  
Harness: Flask-threaded Windows (not Gunicorn). WSL available; Docker daemon not used.  
No hotfix / no PR / no main / no Railway.

## Verdict (gates)

| Gate | Result |
|------|--------|
| CONTROL_CALIBRATED | **yes** (4 clients: `/api/game-state` p50≈286–302 ms, p95≈475–545 ms, slow5=0) |
| SYSTEM_FAILURE_MODE | **yes** (from REPRO-002 at aggressive load on stable tree) — **not** re-triggered at calibrated 4-client load |
| HISTORICAL_REGRESSION | **no** (A / B / C maintenance penalties nearly identical) |
| ROOT_CAUSE | **under investigation** |
| FULL_RECONCILE_INVOLVED | **no** (runtime_state normalized; ranking modes `dirty`/`skip` only) |

## What REPRO-002 did / did not prove

**CONFIRMED (keep):** multi-route stalls under synthetic scale + maintenance on the stable `9027ec0` tree; SQLite writer contention as a mechanism.

**NOT CONFIRMED:** that this was the 2026-08-29 Production incident; that STATE-012/013 caused it; that `run_maintenance_bag` is one long transaction; that “sidecar-only” is missing (already production architecture).

## Harness footgun fixed mid-run

First differential pass used **relative** `GC_DB_PATH` while `cwd=worktree`. Historical trees opened a **256 KB empty DB** under the worktree and returned mostly **401** — false “fast” baselines (~22 ms p50).

Fix: always `Path.resolve()` absolute `GC_DB_PATH`, reject tiny seed copies, require `auth_ok_ratio` ≥ 0.8 on `/api/game-state`.

Invalid run artifacts: `artifacts/concurrency_repro/repro003/` (discard for A/B/C claims).  
Valid run artifacts: `artifacts/concurrency_repro/repro003_v2/`.

## Control (no maintenance)

Current-branch control (`repro003/control_calibrated_report.json`):

- clients=4, duration=60s
- `/api/game-state` p50=285.6 p95=486.8 p99=575 max=587
- `/galaxy` p50=1143 p95=1496
- slow5=0, rps≈7.0

Conclusion: REPRO-002’s ~2 s / ~3.4 s p50s were **harness-overdrive** (default 15 clients), not a representative idle baseline.

## Idle stage attribution (no HTTP)

`_repro003_staged_maint.py` modes on normalized 161 MB seed:

| Stage | Typical ms |
|-------|------------|
| ranking (dirty/skip) | ~5–10 |
| fleet | ~15–18 |
| account_deletions | ~4–6 |
| privacy_retention | ~5 |
| sqlite_backup (first of day) | **~400–500** |
| heartbeat | ~6 |
| **bag total (idle)** | **~0.5 s** (not 18–23 s) |

Dominant idle stage: **sqlite_backup** (daily copy). Ranking full-reconcile avoided by setting `ranking_full_reconcile_last=now`.

## Historical differential (valid)

Identical absolute seed copy, normalized runtime_state, clients=4, duration=60s, reps=3, maint interval≈12s, Flask-threaded.

Maintenance penalty = maint − control (game-state):

| Tree | Control p95 / p99 | Maint p95 / p99 | Penalty p95 / p99 | slow5 |
|------|-------------------|-----------------|-------------------|-------|
| A `9027ec0` | 475 / 568 | 501 / 610 | **+25 / +43** | 0 / 0 |
| B STATE-012 `b0fade84` | 528 / 632 | 529 / 614 | **+1 / −17** | 0 / 0 |
| C STATE-013 `7f3990b` | 545 / 663 | 576 / 673 | **+31 / +10** | 0 / 0 |

In-process stage holds under this load (45 maint ticks): fleet p95≈27 ms, ranking p95≈7.5 ms, backup skipped (`already_today`), no stage near multi-second writer occupancy. Wall-clock “STAGED ~1.4 s” is mostly **subprocess bootstrap**, not continuous `BEGIN IMMEDIATE`.

Gate: C is **not** significantly worse than A → **HISTORICAL_REGRESSION = no**.

## Architecture clarifications (do not sell as new fixes)

1. Sidecar maintenance (`GC_MAINTENANCE_WORKER=1`, `GC_EMBEDDED_CRON=0`) is already intended production shape.
2. `run_maintenance_bag` is an orchestrator; fleet already splits stages with `hold_ms`.
3. Ranking full reconcile is a real expensive path — seed must normalize `runtime_state` or every first tick becomes a synthetic “daily safety net”.

## Windows / Gunicorn

- Native Windows + `pip install gunicorn` is **not** a production claim.
- WSL2: available (`wsl_ok`).
- Docker: client present; daemon not used in this pass.
- All numbers below are **Flask-threaded harness** results.

## Root-cause gate

```
REPRODUCED SYSTEM FAILURE MODE = yes   (REPRO-002, aggressive load, stable tree)
REPRODUCED HISTORICAL REGRESSION = no  (REPRO-003 A≈B≈C penalties)
ROOT CAUSE = under investigation
```

STATE-012 / STATE-013 are **not** implicated by this differential.

## High-load check on A (reconnect REPRO-002)

Tree A only, clients=12, duration=90s, absolute seed, auth_ok=1.0:

| Mode | gs p50 / p95 / max | slow5 |
|------|--------------------|-------|
| CONTROL (no maint) | 1368 / 3090 / 5789 | **5** |
| MAINT | 1282 / 3344 / 5088 | **6** |
| Penalty p95 | | **+254 ms** |

In-process stage holds under that load (selected ticks):

- First tick: `sqlite_backup` **628 ms**, fleet 174 ms, heartbeat 437 ms
- Contended tick: fleet **2299 ms**, heartbeat **1745 ms** (same bag)
- Contended tick: heartbeat **5423 ms**, fleet **999 ms**

So short stages **do** stretch into multi-second writer occupancy under harness overload — without needing one monolithic bag transaction. Ranking stayed `dirty`/`skip` (no full reconcile).

Interpretation: at 12 clients the Flask-threaded harness is **already** multi-second slow without maintenance. Maintenance adds only a modest p95 penalty. This strengthens: REPRO-002 system failure mode ≠ proven historical STATE-012/013 regression.

## Next action

Done as **REPRO-004** (`docs/incidents/2026-08-30-concurrency-repro-004.md`): Docker Gunicorn+gevent+sidecar. Keep REPRO-002/003/004 local; **do not push/PR** until asked.

## Scripts

- `scripts/prod_infinity_load_repro003_differential.py`
- `scripts/_repro003_staged_maint.py`
- `scripts/_repro003_print_stages.py` / `_repro003_print_diff.py`
