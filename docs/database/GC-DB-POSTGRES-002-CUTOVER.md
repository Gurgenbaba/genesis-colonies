# GC-DB-POSTGRES-002 — Production Cutover Preparation

> **Mode:** PREPARATION / REHEARSAL ONLY  
> **Base:** `main` @ `7af2cd2b50dccee506819366a7a79f0c04457923` (PR #127 merge)  
> **Prerequisite:** [GC-DB-POSTGRES-001-PHASE1.md](GC-DB-POSTGRES-001-PHASE1.md) — technical READY YES  
> **This ticket does NOT:** switch production, change Railway variables, detach/delete the SQLite volume, or open live Postgres writes.

**CUTOVER RUNBOOK READY: YES**

---

## 0. Scope and hard rules

| Rule | Meaning |
|------|---------|
| No live switch in this ticket | Runbook + config matrix only |
| No Railway mutation here | Operators execute later under explicit approvals |
| SQLite volume retained | Keep `/data` mounted through acceptance window |
| Dual-process switch | Web (gunicorn) + maintenance sidecar share one container env — they switch together |
| Case-B rollback | After Postgres accepts live player writes, pointing back at old SQLite is **unsafe** |

Prerequisite evidence (001, not re-proven here):

- 192 application tables, 426 795 rows, 0 mismatches, 103 sequences reset  
- Parity A–F PASS  
- Linux Gunicorn `gthread` w1/t4 PASS on imported disposable PG  

---

## 1. Current main audit (post #127)

### 1.1 Hardening on `main`

Merged via PR #127 → merge commit `7af2cd2b`. Production deploy of that SHA ships dual-backend hardening while remaining on SQLite until env switch.

### 1.2 Start command (verified in repo)

Owner: [`scripts/docker-entrypoint.sh`](../../scripts/docker-entrypoint.sh) ← Dockerfile `CMD`.

| Knob | Default | Production expectation |
|------|---------|------------------------|
| `GUNICORN_WORKER_CLASS` | `gthread` | `gthread` |
| `GUNICORN_WORKERS` | `1` | `1` |
| `GUNICORN_THREADS` | `4` (floored to ≥2 for gthread) | `4` |
| Timeout | `--timeout 120` | unchanged |
| Bind | `0.0.0.0:$PORT` | Railway `PORT` |

Effective cmdline:

```text
gunicorn -k gthread -w 1 --threads 4 -b 0.0.0.0:$PORT --timeout 120 app:app
```

Maintenance sidecar (same container, same env):

| Knob | Default | Effect |
|------|---------|--------|
| `GC_MAINTENANCE_WORKER` | `1` | Starts `scripts/run_maintenance_worker.py` under respawn loop |
| `GC_EMBEDDED_CRON` | forced `0` when sidecar on | Gunicorn must not own the bag |

**Do not** add a separate Railway ranking/fleet worker service for the initial cutover. Sidecar + web share `DATABASE_URL`.

Optional later (not required for first cutover): `scripts/run_game_worker.py` as a dedicated process — only after Postgres is stable and architecture docs update.

### 1.3 Backend selection owners

| Concern | Owner |
|---------|-------|
| Backend choice | `game/db.py` → `get_db_backend()` ← `GC_DB_BACKEND` (default `sqlite`) |
| Postgres pool | `game/db_pg.py` |
| Production PG gate | `game/config.py` → `validate_config` requires `GC_ALLOW_POSTGRES_PROD=1` when `APP_ENV=production` and backend=`postgres` |
| Health proof | `/health` → `checks.database.backend` |
| Migrations | `migrate.py` on every container start (entrypoint) |
| Import | `scripts/pg_import_sqlite.py` |

Silent fallback does **not** exist: `GC_DB_BACKEND=postgres` without a usable pool raises; production without `GC_ALLOW_POSTGRES_PROD` fails config → `/health` **fail**.

### 1.4 Environment variable inventory

#### Backend selection

| Variable | Role |
|----------|------|
| `GC_DB_BACKEND` | `sqlite` \| `postgres` — authoritative selector |
| `DATABASE_URL` | Postgres DSN when backend=`postgres` (`postgresql://…`). SQLite file URLs may map to `GC_DB_PATH` via `config._normalize_database_url`. A Postgres URL is **ignored** while backend stays `sqlite` (warning only). |
| `GC_DB_PATH` | SQLite file path (prod: `/data/game.db`). Keep set after cutover for volume writability probes, TTS cache layout, and rollback readiness. |
| `GC_ALLOW_POSTGRES_PROD` | Must be `1`/`true`/`yes`/`on` for production Postgres boot. Unset today. |
| `GC_TEST_POSTGRES_URL` | Import/test alternate DSN (importer only; not production). |

#### Pool / timeouts (Postgres)

| Variable | Default | Role |
|----------|---------|------|
| `GC_PG_POOL_MAX` | `10` | `psycopg_pool` max size |
| `GC_PG_CONNECT_TIMEOUT` | `20` | connect timeout (s) |
| `GC_PG_POOL_TIMEOUT` | `30` | checkout timeout (s) |
| `GC_PG_STATEMENT_TIMEOUT` | `60s` | session `statement_timeout` |
| `GC_PG_LOCK_TIMEOUT` | `15s` | session `lock_timeout` |

#### Process / maintenance

| Variable | Default | Role |
|----------|---------|------|
| `GUNICORN_WORKER_CLASS` | `gthread` | HTTP worker class |
| `GUNICORN_WORKERS` | `1` | HTTP workers |
| `GUNICORN_THREADS` | `4` | threads when gthread/sync |
| `GC_MAINTENANCE_WORKER` | `1` | Sidecar bag owner |
| `GC_EMBEDDED_CRON` | prod default on unless sidecar forces off | In-process bag (legacy) |
| `GC_EMBEDDED_CRON_SEC` | `60` | Bag interval |
| `GC_EMBEDDED_BACKUP` | on | Daily SQLite online backup under `/data/backups/` |
| `GC_EMBEDDED_BACKUP_KEEP` | `7` | Retention |
| `GC_INTERNAL_CRON_TOKEN` | optional | Manual `POST /api/internal/cron/*` |

#### Unrelated but must stay stable

`APP_ENV`/`FLASK_ENV=production`, `SECRET_KEY`, `PUBLIC_BASE_URL`, shop/Discord/SMTP/vote keys — unchanged by cutover.

### 1.5 Processes that must switch together

| Process | How it runs today | Cutover note |
|---------|-------------------|--------------|
| Gunicorn web | Same container | Reads `GC_DB_BACKEND` / `DATABASE_URL` at boot |
| Maintenance sidecar | Same container, same env | Must see Postgres on same deploy restart |
| Railway Postgres plugin | Separate data service | Provisioned before import; not switched by app vars alone |
| Dedicated `run_game_worker` | **Not** in current prod topology | Do not introduce on cutover day |

There is **one** Railway web service. Variable change + redeploy/restart applies to web + sidecar atomically from the operator’s perspective.

### 1.6 Configuration matrix

#### CURRENT SQLITE (production now)

| Variable | Value |
|----------|-------|
| `GC_DB_BACKEND` | `sqlite` |
| `GC_DB_PATH` | `/data/game.db` |
| `DATABASE_URL` | unset **or** non-Postgres / ignored if Postgres URL left set by mistake |
| `GC_ALLOW_POSTGRES_PROD` | unset / `0` |
| `GUNICORN_*` | `gthread` / `1` / `4` |
| `GC_MAINTENANCE_WORKER` | `1` |
| Volume `/data` | **mounted** |
| Proof | `GET /health` → `checks.database.backend == "sqlite"` |

#### FUTURE POSTGRES (after approved switch)

| Variable | Value |
|----------|-------|
| `GC_DB_BACKEND` | `postgres` |
| `DATABASE_URL` | Railway Postgres `postgresql://…` (internal URL preferred) |
| `GC_ALLOW_POSTGRES_PROD` | `1` |
| `GC_DB_PATH` | keep `/data/game.db` (volume retained; not authoritative) |
| Pool knobs | defaults unless ops tunes under load |
| `GUNICORN_*` | keep `gthread` / `1` / `4` for first acceptance window |
| `GC_MAINTENANCE_WORKER` | `1` (re-enable after pre-switch smoke) |
| Volume `/data` | **still mounted** (backups, probes, rollback artifacts) |
| Proof | `/health` → `backend == "postgres"`; config errors empty; no SQLite file opened as game DB |

#### ROLLBACK SQLITE (only Case A — before live PG writes, or after proven zero PG gameplay writes)

| Variable | Value |
|----------|-------|
| `GC_DB_BACKEND` | `sqlite` |
| `GC_DB_PATH` | `/data/game.db` (pre-switch snapshot restored if needed) |
| `GC_ALLOW_POSTGRES_PROD` | unset / `0` |
| `DATABASE_URL` | unset **or** leave Postgres URL but **must not** set backend=`postgres` |
| Redeploy/restart | required |
| Proof | `/health` → `backend == "sqlite"`; integrity of restored file |

**Case B** (Postgres already took live writes): do **not** use this matrix as a data rollback. See §5.

---

## 2. Cutover procedure (chronological)

> Operator executes later. **Human approval gates** are marked ★.

### PRE-CUTOVER

1. ★ Confirm `main` @ target SHA deployed green (CI + Railway deploy success).  
2. Confirm SQLite health: `curl -sS https://www.genesis-colonies.de/healthz` and `/health` → ok, `backend=sqlite`.  
3. ★ Provision / verify Railway PostgreSQL target (empty or wipe-ready). Record DSN privately (never commit).  
4. Verify target: `psql "$DATABASE_URL" -c 'SELECT 1'` (ops shell).  
5. Take a PostgreSQL empty-cluster backup/snapshot (provider snapshot).  
6. Confirm SQLite volume backup path `/data/backups/` recent + create an extra offline copy outside the running volume if possible.  
7. Rehearse rollback Case A config on paper (matrix above).  
8. ★ Announce maintenance window; prepare public maintenance / traffic hold (CDN or temporary outage).  
9. Freeze smoke checklist (§2 PRE-SWITCH SMOKE) and abort thresholds (§4).  
10. ★ Explicit go/no-go for entering WRITE FREEZE.

**Abort thresholds (pre-switch):** any failed integrity check; import row mismatch > 0; skipped application table; sequence behind MAX; `/health` not postgres during PG smoke; any P0 gameplay smoke failure; unexplained error spike.

### WRITE FREEZE

There is **no** first-class `GC_WRITE_FREEZE` flag in application code today. Freeze is **operational**:

1. ★ Place site in maintenance / stop player traffic (CDN maintenance page or equivalent).  
2. Disable async writers for the freeze window:
   - Set `GC_MAINTENANCE_WORKER=0` and `GC_EMBEDDED_CRON=0`, **or** stop the service briefly after traffic is held.  
   - Do not fire `POST /api/internal/cron/*` during freeze.  
3. Confirm no new gameplay writes: traffic held + bag stopped; optionally watch Railway metrics/logs for write queries.  
4. Keep maintenance state explicit in the ops channel until freeze lifts.

Abort if traffic cannot be held or writers cannot be stopped.

### FINAL SNAPSHOT

On the authoritative SQLite file (volume or cold copy after writers stopped):

```bash
# Consistent online copy (preferred API)
python - <<'PY'
import sqlite3, hashlib, pathlib
src = pathlib.Path("/data/game.db")  # adjust if using offline copy path
dst = pathlib.Path("/data/backups/cutover-final.db")
dst.parent.mkdir(parents=True, exist_ok=True)
s = sqlite3.connect(str(src))
d = sqlite3.connect(str(dst))
s.backup(d)
d.close(); s.close()
print("backup_ok", dst)
PY

sqlite3 /data/backups/cutover-final.db "PRAGMA quick_check;"
sqlite3 /data/backups/cutover-final.db "PRAGMA integrity_check;"
# SHA256 of cutover-final.db — record privately
sqlite3 /data/backups/cutover-final.db "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
# Aggregate application row count (sum of user tables) — record privately
```

Record privately (do **not** commit): SHA256, table count, aggregate rows, timestamp, operator.

### POSTGRES PREP

1. Point a **one-shot ops job / local secure shell** at the **target** Postgres (not yet the live web backend).  
2. `GC_DB_BACKEND=postgres DATABASE_URL=… python migrate.py` on empty/fresh DB.  
3. Confirm schema / `migration_history` current.  
4. Ensure no stale gameplay rows (`--wipe` import path or explicit truncate strategy owned by importer).  

### FINAL IMPORT

```bash
export GC_DB_BACKEND=postgres
export DATABASE_URL='postgresql://…'   # target only
# GC_ALLOW_POSTGRES_PROD not required for offline import tooling, but fine if set

python scripts/pg_import_sqlite.py --wipe --sqlite /path/to/cutover-final.db
```

Require:

- Every application table imported (no unexplained skips; `sqlite_sequence` / `migration_history` skip is expected)  
- Per-table row parity = 0 mismatches  
- Total row parity  
- Sequences reset; none behind MAX  
- Invariant checks (use established Phase-1 invariant script **locally**, never commit prod-derived output)  

Abort on any mismatch.

### PRE-SWITCH SMOKE (writes still frozen)

Run app **against Postgres** while public writes remain frozen (temporary process or staging URL — **not** opening players yet):

| Check | Expect |
|-------|--------|
| `/healthz` | alive |
| `/health` | ok, `checks.database.backend=postgres`, config errors empty |
| Login / session | ok (controlled identity) |
| Overview | 200 |
| `/api/game-state` | ok |
| Buildings / Research / Shipyard | render |
| Fleet / Galaxy | render |
| Ranking / Alliance | render |
| World Boss / HoF | render |
| Queue + fleet maintenance bag (single forced tick if needed) | ok, no crash |

★ Only after **all** green: approve SWITCH.

### SWITCH (design only here — see §3)

Minimal env change + restart. Do not execute in this ticket.

### POST-SWITCH (see §4)

Timed observation; controlled test identity for mutations; then ★ lift freeze / reopen traffic.

---

## 3. Switch design (do not execute)

### Minimal production configuration change

On the **web** Railway service (single service topology):

| Action | Variable |
|--------|----------|
| Set | `GC_DB_BACKEND=postgres` |
| Set | `DATABASE_URL=<Railway Postgres URL>` |
| Set | `GC_ALLOW_POSTGRES_PROD=1` |
| Keep | `GC_DB_PATH=/data/game.db` |
| Keep | `GUNICORN_WORKER_CLASS=gthread`, `GUNICORN_WORKERS=1`, `GUNICORN_THREADS=4` |
| Restore after freeze | `GC_MAINTENANCE_WORKER=1` (sidecar on) |

Atomic from operator view: save variables → redeploy/restart **one** web service → entrypoint migrates → gunicorn + sidecar boot on Postgres.

### Startup proof (must capture)

```bash
curl -sS https://www.genesis-colonies.de/healthz
curl -sS https://www.genesis-colonies.de/health
```

Require:

- HTTP 200 on both (after warm start)  
- `checks.database.backend` === `"postgres"`  
- `checks.config.errors` empty (proves allow-flag accepted)  
- Railway logs: entrypoint migrate ok; `[maintenance-worker] started` when sidecar enabled  
- **No** log line implying SQLite game DB open as backend  

### Prove SQLite fallback did NOT occur

| Signal | Pass |
|--------|------|
| `/health` backend | `postgres` |
| Config | no “blocked in production until cutover” |
| Intentionally wrong test (pre-prod only) | backend=`postgres` without allow → health fail |
| `GC_DB_BACKEND=sqlite` with Postgres URL | would stay sqlite — therefore backend env is the switch, not URL alone |

---

## 4. Post-switch acceptance

### Observation window

| Checkpoint | Actions |
|------------|---------|
| **T+0** | `/healthz`, `/health` backend=postgres; login; game-state; logs clean |
| **T+5m** | Galaxy, fleet, queues, ranking; worker heartbeat age OK |
| **T+15m** | Alliance, world boss, HoF; controlled building/research action on **test** identity |
| **T+30m** | Error rate, pool timeouts, deadlock search in logs; no worker crash loop |
| **T+60m** | ★ Go/no-go to declare acceptance; keep SQLite volume |

### Immediate verify list

- `/healthz`, `/health` (`backend=postgres`)  
- Login/auth  
- game-state, galaxy, fleet, queues, ranking, world boss, alliance  
- Building/research actions (test identity only until T+15+)  
- Worker heartbeats (admin runtime / logs)  
- Error logs, pool exhaustion, deadlocks, statement timeouts, worker crashes  

### PASS / FAIL thresholds (recommended)

| Metric | PASS | FAIL → escalate |
|--------|------|-----------------|
| `/health` | ok + postgres | fail/degraded with DB/config errors |
| `/healthz` | alive | down |
| HTTP 5xx rate | ≈ baseline | sustained ≫ baseline |
| Pool timeout errors | none/rare | repeated `GC_PG_POOL_TIMEOUT` |
| Deadlocks | none/rare | repeated |
| Worker crashes | no restart storm | sidecar/gunicorn crash loop |
| Data correctness | smoke actions commit & read back | divergence / Integrity errors |

On FAIL before declaring acceptance: enter emergency maintenance; follow §5.

---

## 5. Rollback

### Case A — Failure **before** Postgres accepts live player writes

Safe: SQLite remains (or is restored as) authoritative.

1. Maintenance / traffic hold.  
2. Set CURRENT SQLITE matrix (`GC_DB_BACKEND=sqlite`, clear allow flag, keep `GC_DB_PATH`).  
3. Restart web service.  
4. Prove `/health` → `backend=sqlite`.  
5. If final snapshot replaced `/data/game.db`, restore from `cutover-final.db` / dated backup before reopen.  
6. Re-enable maintenance worker.  
7. ★ Reopen traffic.

### Case B — Failure **after** Postgres has accepted live writes

**Do not** point the app back at the old SQLite file and reopen. That loses or diverges writes.

1. ★ Emergency maintenance / write freeze immediately.  
2. Keep `GC_DB_BACKEND=postgres` (or stay down) until reconciliation plan exists.  
3. Take a **PostgreSQL** backup/dump **now** (authoritative candidate).  
4. Preserve SQLite volume untouched for forensic diff.  
5. Data reconciliation options (choose under ★ approval):  
   - Fix-forward on Postgres (preferred if corruption is narrow)  
   - Restore Postgres from pre-incident PG backup and replay known gap (if available)  
   - Build a one-off reverse sync only with explicit diff tooling — **not** “flip env to sqlite”  
6. Document player-visible impact; communicate.  

SQLite volume: **never delete** during the initial PostgreSQL acceptance period.

---

## 6. Data safety (Git and artifacts)

Never commit:

- `*.db`, SQLite snapshots, PG dumps  
- Player records, emails, message bodies, payment data  
- Secrets, DSNs, raw production audit JSON with PII  

Commit only aggregate/sanitized evidence (counts, pass/fail, durations). Local rehearsal helpers under `scripts/_phase1_*` and `artifacts/` stay untracked.

---

## 7. Operator cheat sheet (Phase 7 summary)

### 1. Exact current backend configuration

`GC_DB_BACKEND=sqlite`, `GC_DB_PATH=/data/game.db`, `GC_ALLOW_POSTGRES_PROD` unset, gunicorn `gthread` w1 t4, maintenance sidecar on, volume `/data` mounted.

### 2. Exact future PG configuration

`GC_DB_BACKEND=postgres`, `DATABASE_URL=postgresql://…`, `GC_ALLOW_POSTGRES_PROD=1`, keep `GC_DB_PATH` + volume, same gunicorn topology, sidecar on after smoke.

### 3. Web/worker switch matrix

One Railway web service; gunicorn + maintenance sidecar share env; switch = variable set + restart; no second worker service on day one.

### 4. Cutover procedure

PRE-CUTOVER → WRITE FREEZE → FINAL SNAPSHOT → POSTGRES PREP → FINAL IMPORT → PRE-SWITCH SMOKE → SWITCH → POST-SWITCH (§2–§4).

### 5. Write-freeze procedure

Traffic hold + disable bag (`GC_MAINTENANCE_WORKER=0` / `GC_EMBEDDED_CRON=0` or stop service) + no internal cron POSTs. No in-app freeze flag yet.

### 6. Final import procedure

Fresh migrate → `python scripts/pg_import_sqlite.py --wipe --sqlite cutover-final.db` with `GC_DB_BACKEND=postgres` + target `DATABASE_URL` → parity + sequences + invariants.

### 7. Verification commands

```bash
curl -sS https://www.genesis-colonies.de/healthz
curl -sS https://www.genesis-colonies.de/health
# Inspect checks.database.backend and checks.config.errors
```

Plus sqlite3 PRAGMA/SHA256 on snapshot; importer report; controlled UI smoke.

### 8. Post-switch smoke checklist

healthz/health, login, game-state, overview, buildings, research, shipyard, fleet, galaxy, ranking, alliance, world boss, HoF, queue/fleet maintenance, test-identity mutations.

### 9. Monitoring thresholds

T+0/5/15/30/60; FAIL on health not postgres, 5xx spike, pool/deadlock storms, crash loops (§4).

### 10. Rollback procedure

Case A → SQLite matrix + optional file restore. Case B → freeze, PG backup, reconcile; **no** naive SQLite re-point (§5).

### 11. Estimated maintenance window

| Phase | Estimate |
|-------|----------|
| Announce + freeze + snapshot | 15–30 min |
| Migrate + import (~427k rows class) | 15–45 min (network-bound) |
| Pre-switch smoke | 20–40 min |
| Switch + T+60 observation | 60 min |
| **Player-visible freeze (until reopen)** | **≈ 60–120 min** (buffer for abort) |

### 12. Steps requiring explicit human approval (★)

1. Enter write freeze / public maintenance  
2. Provision/use production Postgres + handle secrets  
3. Approve final import target wipe  
4. Approve production env switch (`GC_DB_BACKEND` / `DATABASE_URL` / `GC_ALLOW_POSTGRES_PROD`)  
5. Lift freeze / reopen traffic  
6. Declare T+60 acceptance  
7. Any Case B reconciliation strategy  
8. Any future delete/detach of SQLite volume (forbidden in initial acceptance; separate ticket)

---

## 8. Explicit non-actions (this ticket)

- [x] No Railway variable changes performed  
- [x] No production `DATABASE_URL` switch  
- [x] No SQLite volume delete/detach  
- [x] No live cutover execution  

---

## Regel 19

| | |
|--|--|
| Replaced | none (docs-only preparation) |
| Removed | none |
| Call-sites | n/a |
| Dead-code search | n/a — runbook references existing owners only (`docker-entrypoint`, `db`/`db_pg`, `migrate`, `pg_import_sqlite`, health/config gates) |

---

**CUTOVER RUNBOOK READY: YES**
