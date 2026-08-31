# GC-DB-POSTGRES-001 — Phase 1 Final Acceptance

> **Mode:** AUDIT / STAGING ONLY (no production cutover)  
> **Base:** `origin/main` @ `200c1568ac975c594cc09ecd6eaeb11fc3ce0a0f`  
> **Branch:** `audit/gc-db-postgres-001-phase1`  
> **Date:** 2026-08-31  
> **Production mutation/cutover:** none  
> **Production read access:** SQLite snapshot creation only (read-only `/tmp` copy; no Railway config/data mutation)

---

## POSTGRES READY: **YES**

Strict gate satisfied:

1. Real production-copy import succeeded (426 795 rows, 0 mismatches)  
2. Logical invariants + sequences green  
3. App boots on imported disposable PostgreSQL (no SQLite fallback)  
4. Functional smoke green  
5. **Native Linux Gunicorn `gthread` workers=1 threads=4** availability green  
6. **PostgreSQL parity A–F re-run on final worktree state** all PASS  
7. No remaining P0/P1 PG/data-integrity blockers

This is **not** a Railway cutover.

---

## Production snapshot metadata

| Item | Value |
|------|-------|
| Master (never modified) | local offline snapshot `gc-prod-snapshot-20260831-110452.db` (outside repo) |
| Working copy (import source) | local `gc-prod-working-copy.db` (outside repo) |
| SHA256 (master = working) | `89EA276CA714D7209E719E3F442A23D5D5BC5A034F653EC183712144CC6D097B` |
| PRAGMA quick_check / integrity_check | ok / ok |
| Total SQLite tables | **193** |
| Application tables | **192** |
| SQLite-internal only | `sqlite_sequence` (excluded from import) |
| Total application rows | **426 795** |

Disposable PG: Docker `gc-pg-phase1` → `gc_phase1_prod` @ `127.0.0.1:5433` (not Railway).

---

## Evidence summary

| Gate | Result |
|------|--------|
| Dirty Phase-1 work preserved + extended | ✅ |
| Importer dry-run (192 tables, FK order) | ✅ |
| Fresh PG migrate | ✅ through `157_*` |
| Wipe-import production working copy | ✅ `sequences_reset=103` |
| Per-table row parity | ✅ 426795 = 426795 |
| Logical invariants | ✅ |
| App boot on imported PG | ✅ backend=postgres |
| Functional smoke | ✅ |
| **Linux Gunicorn gthread w1/t4 load** | ✅ see §5 |
| **Parity A–F on final branch state** | ✅ A–F PASS (isolated processes) |
| Waitress threads=4 (Windows host only) | supplemental only — **not** the READY gate |

---

## 1. Existing foundation (unchanged owners)

`game/db.py`, `game/db_pg.py`, `game/sql_pg_rewrite.py`, `schema_bootstrap.py`, `migrate.py`, `scripts/pg_import_sqlite.py`, `tests/pg_fixtures.py`.

---

## 2. Delta fixes

### Pre-existing dirty work (preserved)

| Area | Fix |
|------|-----|
| `migrate.py` | Word-boundary BEGIN/COMMIT/ROLLBACK |
| `combat_hof.py` | Portable JSON via `messages._json_text_path_sql` |
| Schema probes | `table_exists` / `table_columns` / `column_exists` |
| ON CONFLICT increments | Table-qualified target columns |

### Found with real production-copy import / smoke

| Defect | Fix |
|--------|-----|
| int32 overflow (23 columns) | BIGINT widen + SQLite overflow scan before import |
| `player_unlocks.created_at` text timestamps | Importer epoch coercion |
| `COALESCE(ps.score_*, 0)` vs TEXT big-score | `'0'` defaults + `SUM(CAST(... AS NUMERIC))` |
| World Boss `GROUP BY` | include `a.tag, a.name` |

---

## 3. Import statistics

| Metric | Value |
|--------|------:|
| Application tables | 192 |
| Row mismatches | 0 |
| Total rows SQLite / Postgres | 426795 / 426795 |
| Sequences reset | 103 |
| Sequences behind MAX | 0 |
| Coerced values | `player_unlocks.created_at` × 681 |

---

## 4. Functional smoke (imported PG)

Isolated disposable identity for mutations. Pages + `/api/game-state` + queue/fleet heartbeats + HoF list/sync: **ok**.

Local-only evidence was produced under the Phase-1 audit workspace and intentionally excluded from Git because it is derived from production-copy testing.

---

## 5. Native Linux Gunicorn gthread w1/t4

| Item | Value |
|------|-------|
| Environment | Linux Docker `python:3.12-slim` container `gc-pg-gunicorn` |
| Cmdline | `gunicorn -k gthread -w 1 --threads 4 -b 0.0.0.0:8765 --timeout 120 app:app` |
| DB | `GC_DB_BACKEND=postgres` → disposable `gc_phase1_prod` via `host.docker.internal:5433` |
| Backend proof | `/health` database.backend = **postgres** |
| Worker crashes | 0 |
| Requests | 120 |
| Errors / timeouts | 0 / 0 |
| Status codes | 200 × 120 |
| healthz p50 / p95 / p99 / max | 33.8 / 39.8 / 49.6 / 52.9 ms |
| Pool exhaustion / deadlocks / DB correctness errors | none observed |

Windows Waitress threads=4 remains a supplemental host probe only.

---

## 6. Parity A–F (final worktree state)

Re-run after all Real-Data fixes; **not** earlier-session results. Each block in its own pytest process against disposable `gc_phase1`:

| Block | Result |
|-------|--------|
| A Auth | PASS |
| B Economy | PASS |
| C Queues | PASS |
| D Fleet/Combat | PASS |
| E Evolution | PASS |
| F Race/restart | PASS |

Detailed local-only parity output was intentionally excluded from Git.

---

## 7. Cutover / rollback (DOCUMENT ONLY)

Write-freeze → SQLite backup retained → migrate empty PG → import frozen copy → verify → smoke → open writes.  
Preferred rollback before reopen: do not switch; SQLite remains authoritative. Never delete SQLite volume on first cutover.

---

## 8. Remaining risks (non-blocking)

| Risk | Severity |
|------|----------|
| Railway staging smoke still pending (ops) | P2 cutover ticket |
| `/health` deep readiness vs SECRET_KEY in some envs | P2 |
| Lexical TEXT score ORDER BY in some SQL paths | P2 (Python authority for big-score) |

---

## 9. Status (closed)

Hardening merged via **PR #127** → `main` @ `7af2cd2b`. Production-derived databases/raw artifacts and local Phase-1 helper scripts remain outside Git.

**GC-DB-POSTGRES-001 closed.** Next: [GC-DB-POSTGRES-002-CUTOVER.md](GC-DB-POSTGRES-002-CUTOVER.md) (preparation/rehearsal only — **no** automatic Railway cutover).

---

## Regel 19

| | |
|--|--|
| Replaced | int32 assumptions; text-timestamp import; score COALESCE int; loose GROUP BY |
| Owners reused | `messages._json_text_path_sql`, `game.db` schema helpers, importer/schema_bootstrap |
| No parallel DB stack | dual-backend retained intentionally |
