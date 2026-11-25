# GC-PROD-INFINITY-LOAD-REPRO-006 — Historical Trigger / Writer Provenance

Date: 2026-08-30  
Branch: `fix/prod-infinity-load-concurrency-repro`  
Harness: Docker Gunicorn **gevent w1** + maintenance sidecar + `sitecustomize` TX provenance (no production edits)  
Seed: ~161 MB absolute `GC_DB_PATH`  
No Railway / main / merge. #125 untouched.

## Two root-cause concepts

| Concept | Status |
|---------|--------|
| **SYSTEM FAILURE MECHANISM** | **confirmed** (unchanged from REPRO-005) |
| **HISTORICAL INCIDENT TRIGGER** | **plausible** (named holders; isolation gate C not fully cleared) |

## Goal

Not prove that a lock can freeze the service (already done).  
Find **who holds** the writer lock (HOLD) vs who only **waits** (WAIT), and whether continuous occupancy / thundering writers explain freezes.

## Instrumentation (harness only)

`scripts/repro006_hooks/sitecustomize.py` patches `game.db.begin_write_transaction` / `commit` / `rollback`:

- `BEGIN_ATTEMPT` / `BEGIN_ACQUIRED` / `COMMIT` / `ROLLBACK`
- `wait_ms` vs `hold_ms` strictly separated
- owners: `fleet_worker`, `game_state_queue_finish`, `ranking_*`, `sqlite_backup`, route-named HTTP, etc.
- `GAME_STATE_POLL` flags: `fleet_dirty`, `queue_due`

Artifacts: `artifacts/concurrency_repro/repro006/`

## Busy timeout (read-only)

| Setting | Value | Source |
|---------|-------|--------|
| `sqlite3.connect` timeout | 30 s | `game/db.py` |
| `PRAGMA busy_timeout` | 20000 ms | `game/db.py` |
| `begin_write_transaction` retries | 12 | `game/db.py` |

No production config changed.

---

## SYSTEM FAILURE MECHANISM

```
confirmed
```

(synchronous sqlite3 in a single gevent worker can stall all dynamic HTTP including `/healthz` — REPRO-005)

---

## LONGEST WRITE HOLDER

| Owner | max hold | notes |
|-------|----------|-------|
| **fleet_worker** (`maintenance_sidecar`) | **~3.5–3.9 s** | Dominant across T0–T10 when sidecar on |
| `game_state_queue_finish` | ~1.0–1.3 s | Second when due queues / no maint |
| `game_state_write` | ~0.5–0.7 s | T0 without maint |

Example (T3 matrix): `fleet_worker` hold 3580 ms — not a waiter mislabeled as holder.

## LONGEST WRITE WAIT

| Owner | max wait | notes |
|-------|----------|-------|
| **chat** (`/api/chat/bootstrap`) | **~2.1–4.5 s** | Typical longest waiter under matrix load |
| notifications / misc | lower | |

Thunder (8 clients): measured `BEGIN` waits were often **&lt;40 ms** while `/healthz` froze **12–29 s**.  
Interpretation: freezes are often **worker-starvation from long sync HOLD / heavy request work** (sqlite3 does not yield to gevent), not only long `busy_timeout` waits.

## LONGEST CONTINUOUS WRITER OCCUPANCY

| Metric | Typical |
|--------|---------|
| `writer_occupancy_percent` | **~10–20 %** |
| `longest_continuous_writer_busy_window_ms` | **~3.5–3.9 s** (matches max fleet_worker hold) |

Not a “96 % continuous writer herd with 600 ms max hold” pattern in this harness.  
Pattern is closer to: **occasional multi-second holders** + **serialized gevent request processing** on a large DB.

## DOMINANT HOLDER / WAITER

- **DOMINANT_HOLDER:** `fleet_worker` (when maintenance sidecar present)
- **DOMINANT_WAITER:** `chat` (HTTP write/bootstrap contending or queued behind holds)

## GAME-STATE WRITE RATE

Per instrumented polls (T3):

- ~**150–180 write TX / 100 GETs** → nearly every poll opens a write path under due work
- Polls frequently see `fleet_dirty=true` / `queue_due=true`

## THUNDERING HERD HOLDER (8 clients, T3)

- `healthz` p95 ≈ **29 s**, `game-state` p95 ≈ **12 s**, freeze_windows ≥ 5
- Freeze windows correlated with:
  - **`fleet_worker` holds up to ~3.6 s**, or
  - bursts of **`game_state_queue_finish`** (~0.4–1.1 s each)
- Ranking / backup appeared secondary in these windows (`ranking_dirty` tens of ms)

## State matrix (gevent w1 + maint)

All of T0, T1, T2, T3, T5, T6, T10: **stall=true**, holder=`fleet_worker`.

| Trigger | gs p95 | healthz p95 | max hold |
|---------|--------|-------------|----------|
| T0 normalized | ~8.9 s | ~18 s | 3.4 s fleet_worker |
| T1 due fleets | ~11.6 s | ~19 s | 3.1 s |
| T2 due queues | ~9.3 s | ~12 s | 3.9 s |
| T3 fleets+queues | ~7.7 s | ~17 s | 3.6 s |
| T5 full reconcile | ~8.2 s | ~16 s | 3.1 s |
| T6 backup due | ~9.1 s | ~13 s | 2.7 s |
| T10 combined | ~8.9 s | ~17 s | 2.9 s |

**FULL RECONCILE / BACKUP:** involved as states, **not primary** holders in provenance.

## Isolation (causal gate C)

### T3 fleets+queues · 8 clients

| | maint ON | maint OFF |
|--|----------|-----------|
| Dominant holder | `fleet_worker` | `game_state_queue_finish` |
| healthz p95 | ~28.7 s | ~27.8 s |
| stall | yes | **yes** |

`stall_removed_without_maint = false`

### T0 normalized · 4 clients

| | maint ON | maint OFF |
|--|----------|-----------|
| Dominant holder | `fleet_worker` (~3.2 s) | `game_state_write` (~0.56 s) |
| healthz p95 | ~17 s | ~13 s |
| stall | yes | **yes** |

Removing the longest named maint writer **does not** clear multi-route `/healthz` freeze under this seed + gevent w1.  
HTTP poll/page writes (and/or non-yielding sync work on the large DB) are sufficient alone.

## Roles

| Factor | Role |
|--------|------|
| **MAINTENANCE** | **primary** for longest named holds (`fleet_worker`) when sidecar on |
| **HTTP SAFETY NET** | **co-primary** — alone keeps stall alive (`game_state_queue_finish` / `game_state_write`) |
| FULL RECONCILE | secondary / not dominant in traces |
| BACKUP | secondary / not dominant in traces |

## WEBSOCKET GTHREAD GATE

```
partial
```

5-minute gthread w1/t4 soak (`websocket_gate.json`):

| Check | Result |
|-------|--------|
| Entrypoint override present | yes (`GUNICORN_WORKER_CLASS`) |
| `/ws/galaxy` route present | yes |
| Live WS connect + reconnect | attempted; **0 push messages** in quiet soak (closes 1000) |
| Parallel `/healthz` during soak | **148/148 OK**, p95 ≈ **39 ms** |
| HTTP under gthread (no maint) | `/healthz` p95 ≈ **29 ms**; game-state still multi-second on large DB |

**Emergency read:** gthread keeps `/healthz` live under this load — viable **HTTP availability** mitigation.  
**WS read:** live galaxy push not demonstrated in this quiet soak → gate stays **partial**, not pass.  
Not a root fix for SQLite contention.

## HISTORICAL INCIDENT TRIGGER

```
plausible
```

**Why not `confirmed` yet:** gate C (remove named owner → stall disappears) fails for `fleet_worker` alone.  
**Why `plausible`:** named production-like writers (`fleet_worker`, poll `game_state_*`) reproducibly co-occur with multi-route + `/healthz` freezes under gevent w1 on a production-sized DB; STATE-012/013 remain off the causal trail.

Two structural stories both fit evidence:

1. **Named long holder:** `fleet_worker` HOLD multi-seconds → gevent worker starved.  
2. **HTTP write / heavy sync path:** even without maint, poll/page writes on large DB serialize the single gevent worker into multi-second freezes (max single hold can be &lt;1 s).

## NEXT MINIMAL FIX (proposal only — do not implement here)

1. **Emergency (entrypoint already supports):** `GUNICORN_WORKER_CLASS=gthread` after WS soak gate — improves HTTP availability under lock/hold; does not remove SQLite contention.  
2. **Structural A:** cadence / batch / yield for `fleet_worker` so HOLD cannot occupy multi-seconds without cooperation.  
3. **Structural B:** shrink `/api/game-state` write surface under load (defer/lease queue finish; avoid thundering write polls).  
4. **Structural C (architecture):** make DB access gevent-cooperative or move heavy writers fully off the web worker — addresses both wait and hold starvation.

No production code change in this ticket.

## Scripts

- `scripts/prod_infinity_load_repro006.py`
- `scripts/repro006_hooks/sitecustomize.py`
- `scripts/_repro006_analyze_provenance.py`
- `scripts/_repro006_prepare_triggers.py`
- `scripts/_repro006_topology_entry.sh`
