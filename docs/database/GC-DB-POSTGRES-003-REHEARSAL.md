# GC-DB-POSTGRES-003 — Railway-Like Cutover Rehearsal

> **Mode:** REHEARSAL / TIMING / NON-PRODUCTION  
> **Production:** unchanged (SQLite; no Railway mutation)  
> **Runs:** Run 1 (FAIL, historical) → Run 2 (PASS gates @ `#129` merge)

---

## Rehearsal Run 1 (historical) — FAIL

> **Base:** `main` @ `dc026041d216734360cb42c76a29f9805e9549d6`  
> **Branch:** `rehearsal/gc-db-postgres-003`  
> **Date:** 2026-08-31

## CUTOVER REHEARSAL: **FAIL**

Operational sequence and timing evidence were captured. **FAIL** because the maintenance bag surfaced **P1 PostgreSQL defects** during Write-Open simulation (ranking + world-boss paths). These must be fixed before live cutover approval.

---

## 1. Environment

| Item | Value |
|------|-------|
| Type | **B** — local Docker (Railway-like topology) |
| Postgres | Disposable `gc_rehearsal_003` on Docker `gc-pg-phase1` @ `127.0.0.1:5433` (TCP) |
| App | `python:3.12-slim` container; `migrate.py` + `gunicorn -k gthread -w 1 --threads 4` |
| Network | Container → `host.docker.internal:5433` (simulates remote PG) |
| Application SHA | `dc026041d216734360cb42c76a29f9805e9549d6` |
| Host OS | Windows 11 (orchestration); Linux container for gunicorn |
| Production Postgres | **not used** |

---

## 2. Dataset (sanitized)

| Metric | Value |
|--------|------:|
| Source class | Phase-1 offline production-copy working snapshot (outside Git) |
| SHA256 | `89EA276CA714D7209E719E3F442A23D5D5BC5A034F653EC183712144CC6D097B` |
| Application tables | 192 |
| Application rows | 426 795 |
| Import sequences reset | 103 |

---

## 3. Phase timings (measured)

| Phase | Measured | Notes |
|-------|----------|-------|
| Provision PG | **0.1 s** | `CREATE DATABASE gc_rehearsal_003` |
| Migrate (empty) | **4.6 s** | Fresh schema through `157_*` |
| Import (`--wipe`) | **21.2 s** | ~20 150 rows/s local TCP |
| Migrate post-import | **0.4 s** | **Required** — see §6 |
| Verify (invariants) | **2.1 s** | 0 row mismatches, 0 sequence issues |
| App boot (gunicorn, writers off) | **40.5 s** | Warm container (pip cached); first cold boot ~178 s |
| Read-only smoke | **4.9 s** | Hot-table counts unchanged; see §4 |
| Write-Open (maintenance bag) | **7.0 s** | Bag completed with errors — see §5 |
| Controlled mutation | **26.1 s** | Disposable user id 136; overview + game-state OK |
| Short observation (T+0/5/15) | **15.2 s** | `/healthz` + `/health` 200 throughout |

### 3.1 Timing model

| Line | Seconds | Planning recommendation |
|------|--------:|-------------------------|
| **Technical data path** (migrate + import + post-migrate + verify) | **28** | **15 min** on Railway (+ network/ops buffer) |
| App boot (warm gunicorn) | **41** | **8 min** planning (cold deploy + pip/install buffer) |
| Read-only smoke | **5** | **10 min** planning (operator checklist) |
| Write-Open + sidecar/bag | **7** | **10 min** planning |
| Controlled mutation | **26** | **10 min** planning |
| **Minimum technical path (excl. snapshot)** | **~107** | **~45 min** planning subtotal |
| Operator snapshot/freeze overhead | not timed | **20–30 min** (unchanged from runbook) |
| Post-open observation (T+60) | 15 s rehearsal only | **60 min** production acceptance (separate) |

**Distinction:**

1. **DATABASE FREEZE TIME** — snapshot + import path (~28 s measured locally; plan **15–25 min** with Railway + operator steps)  
2. **PLAYER-VISIBLE MAINTENANCE** — freeze announcement through controlled mutation reopen (~107 s measured warm locally; plan **45–75 min** with buffers; **not** the full T+60 observation)  
3. **POST-OPEN OBSERVATION** — T+60 acceptance window after traffic reopen (runbook §4; not player downtime if reopen follows controlled mutation)

Replace prior **60–120 min** single-number estimate with the table above until a **Railway disposable** rehearsal repeats these phases.

---

## 4. Read-only smoke

**Result:** **PASS** (zero-write gate) with one expected caveat.

| Check | Result |
|-------|--------|
| `/healthz`, `/health` | 200; `backend=postgres` |
| GET pages (login, overview, buildings, …) | 200/302 without auth |
| `/api/game-state` without session | 401 (expected — no auth in RO phase) |
| Hot-table row counts (8 tables) | **unchanged** before/after |

Sidecar/cron remained off. No forced maintenance ticks.

---

## 5. Write-Open simulation

**WRITE_OPEN_APPROVED_AT:** `2026-08-31T15:11:53Z`

Maintenance bag ran once (`source=maintenance_worker`). **Partial FAIL:**

| Symptom | Severity |
|---------|----------|
| `gather_score_stats`: `COALESCE(score_total, 0)` text/int mismatch on PG | **P1** |
| World boss auto-attack: `CASE WHEN $4` non-boolean on PG | **P1** |
| Ranking worker `ok=false` but fleet/post-maint stages proceeded | ops noise |

Case-A rollback would be **closed** after this point in a real cutover.

---

## 6. Controlled mutation

**Result:** **PASS**

- Disposable rehearsal user created (not imported player data)  
- `/overview` 200, `/api/game-state` 200 after login  
- Read-after-write on new user id OK  

---

## 7. Observation (rehearsal)

T+0 / T+5 / T+15: `/healthz` and `/health` remained 200; `backend=postgres`. No pool-timeout or crash-loop observed in this window.

---

## 8. Capacity / speed notes

| Metric | Measured | Planning | Buffer reason |
|--------|----------|----------|---------------|
| Import throughput | ~20k rows/s (local TCP) | 12–15 min | Railway network + CPU class unknown |
| Schema migrate | ~5 s | 3 min | deploy variance |
| Container cold start | ~178 s (incl. pip) | 8 min | Railway build/cache |
| Container warm start | ~41 s | 3 min | restart only |
| Maintenance bag | ~7 s (+ errors) | 10 min | full-universe ranking cost on prod |

---

## 9. Runbook delta vs GC-DB-POSTGRES-002

Do **not** change Write-Open / Case-A safety semantics. Add operational steps:

| Finding | Runbook action |
|---------|----------------|
| `--wipe` import clears `migration_history` (table skipped) | After import, run **`python migrate.py`** again before app boot |
| Bootstrap migration guard uses `GC_DB_PATH` file existence | Keep **`GC_DB_PATH=/data/game.db`** on volume during PG cutover (stub file insufficient on prod — volume file exists) |
| Cold container includes pip/install | Budget separate **cold** vs **warm** restart times |
| Maintenance bag PG errors on prod-scale import | **Block cutover** until ranking/world-boss PG fixes land |

---

## 10. Errors / bottlenecks

1. **P1** — `game/db.py` `gather_score_stats` COALESCE on TEXT big-score columns  
2. **P1** — `world_boss.py` boolean CASE under PG rewrite  
3. **P2** — `codex.py` `datetime('now')` insert on authenticated overview (mutation path; not RO)  
4. **Ops** — first gunicorn boot dominated by pip install (~3 min cold vs ~40 s warm)  
5. **Ops** — `run_maintenance_worker.py --once` can block on leader lock; inline bag preferred for timed rehearsal  

---

## 11. Phase pass/fail matrix

| Gate | Result |
|------|--------|
| Disposable PG provision | PASS |
| Migrate | PASS |
| Full import + parity | PASS |
| Invariants / sequences | PASS |
| PG app boot (writers off) | PASS |
| Read-only smoke (zero-write) | PASS |
| Write-Open bag | **FAIL** (P1 errors) |
| Controlled mutation | PASS |
| P0/P1 cutover blocker | **YES** (maintenance bag) |

---

## 12. Files changed (this ticket)

| File | Role |
|------|------|
| `docs/database/GC-DB-POSTGRES-003-REHEARSAL.md` | This report (sanitized aggregates only) |

Local orchestrator `scripts/_rehearsal_003_run.py` and `artifacts/pg_rehearsal_003/` remain **untracked** (no snapshots/secrets in Git).

---

## 13. Final summary (Phase 15)

1. **Environment:** local Docker PG + Linux gunicorn container  
2. **SHA:** `dc026041`  
3. **Dataset:** 192 tables / 426 795 rows  
4. **Timings:** see §3  
5. **Critical path (warm, excl. snapshot):** ~107 s measured / ~45 min planning  
6. **Recommended maintenance window:** **45–75 min** player-visible (with buffers); observation T+60 separate  
7. **Buffer:** 50% on data path; cold-boot/install extra  
8. **Read-only smoke:** PASS (zero-write verified)  
9. **Write-Open:** FAIL (maintenance bag PG errors)  
10. **Controlled mutation:** PASS  
11. **Bottlenecks:** cold pip install; PG ranking/world-boss SQL  
12. **Runbook deltas:** post-import migrate; timing table; P1 blockers  
13. **Commits:** doc only on `rehearsal/gc-db-postgres-003`  

**CUTOVER REHEARSAL: FAIL**

---

## Regel 19 (Run 1)

| | |
|--|--|
| Replaced | none (rehearsal/doc ticket) |
| Removed | none |
| Call-sites | n/a |
| Dead-code search | n/a |

---

# Rehearsal Run 2 — after PR #129

> **Base:** `main` @ `67391a23e053c69a9fe722b236f67903de4af779` (merge of `#129` / head `96cbb727`)  
> **Branch:** `rehearsal/gc-db-postgres-003-run2`  
> **Date:** 2026-08-31  
> **Dataset:** same offline prod-copy class as Run 1 (SHA256 `89EA276C…097B`, 192 tables / 426 795 rows)  
> **Production:** still SQLite; **no** Railway mutation / no cutover

## CUTOVER REHEARSAL RUN 2: **PASS**

Same topology and phase order as Run 1. Writers off until Write-Open. Run 1 FAIL text above is **retained** (not overwritten).

### Environment

| Item | Value |
|------|-------|
| Type | **B** — local Docker (Railway-like) |
| Postgres | Disposable `gc_rehearsal_003_run2` on `gc-pg-phase1` @ `127.0.0.1:5433` |
| App | `python:3.12-slim` + `migrate.py` + gunicorn gthread w1/t4 |
| Network | `host.docker.internal:5433` |
| Application SHA | `67391a23e053c69a9fe722b236f67903de4af779` |

### Phase timings (measured)

| Phase | Measured | Notes |
|-------|----------|-------|
| Provision PG | **0.2 s** | `CREATE DATABASE gc_rehearsal_003_run2` |
| Migrate (empty) | **4.9 s** | Fresh schema |
| Import (`--wipe`) | **23.6 s** | ~18 125 rows/s |
| Migrate post-import | **0.4 s** | No-op verify — `migration_history` preserved by importer `SKIP_TABLES` |
| Verify (invariants) | **2.6 s** | 0 mismatches, 0 sequence issues |
| App boot (writers off) | **43.0 s** | `status=ok backend=postgres`; sidecar off |
| Read-only smoke | **5.5 s** | Hot tables unchanged; `/api/game-state` 401 unauth OK |
| Write-Open (maintenance bag) | **16.4 s** | `bag.ok=true`; ranking full 128 players / 8.3 s |
| Controlled mutation | **27.1 s** | Disposable user id 136; overview + game-state 200 |
| Short observation (T+0/5/15) | **15.2 s** | healthz/health 200 |

### Timing model (Run 2)

| Line | Seconds | Planning |
|------|--------:|----------|
| Technical data path | **~32** | 15 min Railway buffer |
| Critical path excl. snapshot (warm) | **~124** | ~45 min planning |
| Global rehearsal wall | **140** | — |

### Gate matrix (Run 2)

| Gate | Result |
|------|--------|
| Disposable PG provision | PASS |
| Migrate | PASS |
| Full import + parity | PASS |
| Invariants / sequences | PASS |
| PG app boot (writers off) | PASS |
| Read-only smoke (zero-write) | PASS |
| Write-Open bag (`ok=true`) | **PASS** (Run-1 P1 ranking/`CASE` fixed by `#129`) |
| Controlled mutation | PASS |
| P0/P1 from Run 1 (score COALESCE / WB `CASE WHEN`) | **cleared** |

### Residual finding (does **not** flip bag `ok`)

During fleet post-maint `world_boss` stage, Postgres raised:

`AmbiguousColumn: column reference "alliance_id" is ambiguous`  
in `note_attack_dispatched` UPSERT  
(`COALESCE(excluded.alliance_id, alliance_id)` — bare target column).

- Ranking bag completed successfully (`ok=true`).
- Fleet tick still reported `ok=true` (stage errors are swallowed/logged).
- Same pattern exists at a second site in `world_boss.py` (~L3553).
- **Treat as follow-up PG portability fix before live operator cutover** (qualify target column). Not a re-open of the Run-1 ranking P1.

### Runbook delta correction (vs Run 1 §9)

| Run 1 claim | Run 2 clarification |
|-------------|---------------------|
| `--wipe` clears `migration_history` → post-import migrate required | **False diagnosis.** Importer skips `migration_history`; wipe does not truncate it. Post-import migrate is a cheap no-op. Boot failure was missing stub `GC_DB_PATH`. |

### Final summary (Run 2)

1. SHA `67391a23` (#129 on main)  
2. Same dataset / phases / writers-off until Write-Open  
3. Bag + controlled mutation gates **PASS**  
4. Run-1 P1 blockers **gone**  
5. Residual: qualify `alliance_id` in WB UPSERT before live cutover  
6. Next: Railway disposable timing **or** explicit operator cutover approval  

```text
CUTOVER REHEARSAL RUN 2: PASS
```

### Regel 19 (Run 2)

| | |
|--|--|
| Replaced | none (rehearsal evidence only) |
| Removed | none |
| Call-sites | n/a |
| Dead-code search | n/a (product fix deferred to residual ticket) |
