# GC-PROD-INFINITY-LOAD-REPRO-005 — Worker-Class Causality

Date: 2026-08-30  
Branch: `fix/prod-infinity-load-concurrency-repro`  
Harness: Docker Gunicorn · identical 161 MB seed · absolute `GC_DB_PATH` · auth_ok=1.0  
No production fix / Railway / main / merge. #125 untouched.

## Two root-cause concepts

| Concept | Status |
|---------|--------|
| **SYSTEM FAILURE MECHANISM** | **confirmed** |
| **HISTORICAL INCIDENT TRIGGER** | **under investigation** |

Do **not** treat REPRO-004/005 as proof of the 2026-08-29 trigger. They prove how a multi-route freeze can form.

## Confirmed mechanism

```
synchronous sqlite3 lock wait
+
single gunicorn gevent worker
=
one blocked BEGIN IMMEDIATE can freeze the entire web worker
(including /healthz, which does no DB work)
```

## WORKER CLASS MICROTEST

External process holds `BEGIN IMMEDIATE` for **5 s** on the same DB. Then in parallel:

- **A** — authenticated `/api/game-state` (write path / wait on lock)
- **B** — `GET /healthz` (no DB)
- **C** — `GET /login` (read HTML)

Averages over 3 reps:

| Config | writer_wait (A) | healthz (B) | login (C) |
|--------|-----------------|-------------|-----------|
| **gevent w1** | 7335 ms | **4948 ms** | 7463 ms |
| **gthread w1 t4** | 7393 ms | **9.6 ms** | 119 ms |
| sync w1 (control) | 7384 ms | ~4976 ms | ~7514 ms |
| gevent w2 | 7308 ms | **42 ms** | 108 ms |

Interpretation:

- **gevent w1:** B/C ride with A → worker-level stall (not “route needs the write lock”; `/healthz` needs none).
- **gthread w1 t4:** A still waits ~7 s on SQLite; B/C stay live → OS threads keep serving.
- **sync w1:** not a fix candidate; serialization expected (sometimes B sneaks in before A blocks).
- **gevent w2:** other worker serves B/C while one waits — availability gain, not a root fix.

### Causality gate

| Gate | Result |
|------|--------|
| GEVENT W1: A waits + healthz hangs | **yes** (2/3 reps full hang; 1/3 race where healthz finished before A entered wait) |
| GTHREAD W1/T4: same lock, healthz responsive | **yes** (~10 ms all reps) |
| Only worker-class differs | **yes** |

→ `SYSTEM FAILURE MECHANISM = confirmed`  
→ `GEVENT EVENT LOOP BLOCK = confirmed yes`

## S0 / S5 service (4 clients, 60 s, no sidecar)

### S0 NORMALIZED

| Model | gs p50 / p95 | healthz p95 | slow5 |
|-------|--------------|-------------|-------|
| gevent w1 | 4925 / 9421 | **11964** | 19 |
| **gthread w1 t4** | **960 / 2974** | **2065** | 24 |
| gevent w2 | 3074 / 4395 | 4486 | 19 |
| gthread w2 t2 | 2262 / 3932 | 4218 | 20 |

### S5 FLEET+QUEUES

| Model | gs p50 / p95 | healthz p95 | slow5 |
|-------|--------------|-------------|-------|
| gevent w1 | 5878 / 8812 | **12280** | 22 |
| **gthread w1 t4** | **1497 / 4236** | **1893** | 21 |
| gevent w2 | 4060 / 6170 | 4329 | 21 |
| gthread w2 t2 | 3166 / 5556 | 4426 | 15 |

gthread does **not** remove SQLite writer contention (slow5 still high). It **does** stop one waiting DB call from freezing the whole HTTP surface (`healthz` p95 ~2 s vs ~12 s).

## THUNDERING HERD (S5, 8 clients)

| Model | gs p95 | healthz p95 | slow5 |
|-------|--------|-------------|-------|
| gevent w1 | 13423 | **26237** | 28 |
| gthread w1 t4 | 8940 | **4984** | 47 |

Same story: gthread can show *more* individual slow requests under herd pressure, but the service stays partially alive (`healthz` ~5 s vs ~26 s).

## WEBSOCKET GATE

**partial / not fully soaked**

- Production entrypoint chose gevent for long-lived `/ws/galaxy`.
- Route present; skip-path perf contract exists.
- No dedicated live WS connect/push soak in this ticket.

→ **Do not flip `GUNICORN_WORKER_CLASS` in production** until Galaxy WS is soaked under gthread (or another model).

## BEST WORKER MODEL (experimental only)

For **HTTP availability under sqlite wait**: `gthread -w 1 --threads 4`.

Not a shipped recommendation. Env override already exists:

```sh
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"
```

## Options paper (evaluate only — not implement)

| Option | Freeze risk | WS impact | Notes |
|--------|-------------|-----------|-------|
| **A gthread** | low (HTTP) | **HIGH** | Best match to microtest; needs WS soak |
| **B more gevent workers** | medium | low | Improves availability; more SQLite contention possible |
| **C remove writes from GET/poll** | low | none | Structural; harder correctness |
| **D offload blocking sqlite to threads** | low for loop | none/low | Keep gevent WS; high impl risk |
| **E Postgres** | low | none | Long-term; high migration cost |

## HISTORICAL INCIDENT TRIGGER

**under investigation**

Candidates once mechanism is known: poll write herd, due fleets/queues, backup, full ranking reconcile, HTTP internal cron, unusual runtime_state, client storm, combinations.

STATE-012/013 stay out until new evidence.

## ROOT CAUSE

- **Mechanism:** confirmed — sync sqlite3 wait blocks the sole gevent worker  
- **Trigger:** under investigation  

## NEXT ACTION (proposal only)

1. Keep REPRO-002…005 local; no push/PR/hotfix.  
2. Optional: small Galaxy WS soak under gthread in Docker (still no prod).  
3. Hunt historical trigger with mechanism in mind (what held a write lock long enough on 2026-08-29).  
4. Prefer paper-depth on **C** and **D** before any worker-class prod change.

## Scripts / artifacts

- `scripts/prod_infinity_load_repro005.py`
- `scripts/_repro005_topology_entry.sh`
- `scripts/_repro005_lock_holder.py`
- `artifacts/concurrency_repro/repro005/`
