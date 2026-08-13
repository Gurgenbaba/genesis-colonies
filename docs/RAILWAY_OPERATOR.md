# Railway Operator Guide — Genesis Colonies Production

Operator-only runbook for `www.genesis-colonies.de` (Railway service `genesis-colonies`).  
Not a public self-hosting guide. Code deploy path: [`railway.toml`](../railway.toml) + [`Dockerfile`](../Dockerfile) + [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh).

---

## What is automatic (no external cron)

| Concern | How it runs |
|---------|-------------|
| Migrations | Entrypoint `python migrate.py` on every deploy start |
| Ranking / fleet / vote / account deletions | **Embedded cron** inside the web process (`GC_EMBEDDED_CRON`, default on in production) |
| SQLite backups | Daily online copy to `/data/backups/game-YYYYMMDD.db` (keep 7) |
| Health gate on deploy | `/health` via `railway.toml` |
| Noise deploys | `watchPatterns` skip docs/tests/.cursor |
| CI gate | GitHub Actions workflow `.github/workflows/ci.yml` — enable **Wait for CI** once in Railway UI |

**Do not** set Railway `cronSchedule` on the web service (that model expects the process to exit).  
**Do not** add a second Railway service for SQLite workers (volume is service-bound).

HTTP endpoints `POST /api/internal/cron/*` remain for manual/force runs (`GC_INTERNAL_CRON_TOKEN`).

---

## Architecture constraints (do not override in UI)

| Setting | Required value | Why |
|---------|----------------|-----|
| Builder | Dockerfile (`railway.toml`) | Reproducible prod image |
| Healthcheck | `/health`, timeout 60s | Deploy gate |
| Start | Dockerfile `CMD` → entrypoint | Migrate-on-start needs volume |
| `preDeployCommand` | **Unset** | Pre-deploy container has **no** volume mount |
| `cronSchedule` | **Unset** on web | Would break the always-on gunicorn process |
| Replicas | **1** | Volume + SQLite single-writer |
| Serverless / scale-to-zero | **Off** | Game + embedded cron must stay warm |
| `GUNICORN_WORKERS` | **1** (SQLite) | Multi-worker not used on SQLite production |
| `GUNICORN_WORKER_CLASS` | **gevent** (default) | GC-AST-LIVE: lets WS galaxy-push connections coexist with HTTP on the single worker. Set to `sync` for emergency rollback — WS route/client both degrade gracefully, no redeploy of app code needed |
| Separate ranking worker service | **Do not create** | Volume is service-bound |

---

## One-time Railway / DNS checklist

Still manual (platform/registrar) — do once, then push-to-deploy is enough:

### 1. DNS & domains

- [ ] `www.genesis-colonies.de` healthy on Railway
- [ ] Apex `genesis-colonies.de` DNS finished (CNAME/ALIAS/ANAME per Railway)
- [ ] `PUBLIC_BASE_URL=https://www.genesis-colonies.de`
- [ ] TLS green for both hosts

### 2. Wait for CI (one toggle)

Repo ships [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) (smoke on `push` to `main`).

- [ ] Railway → **Wait for CI → Enable** (not available in `railway.toml`)
- [ ] GitHub Required Checks = app CI (`CI / smoke`), **not** GitHub Pages
- [ ] Prefer Pages Source: None — see [CONTRIBUTING.md](CONTRIBUTING.md)

### 3. Environment variables

| Variable | Expected |
|----------|----------|
| `APP_ENV` / `FLASK_ENV` | `production` |
| `FLASK_DEBUG` | `0` |
| `SECRET_KEY` | Strong random |
| `GC_DB_BACKEND` | `sqlite` until cutover |
| `GC_DB_PATH` | `/data/game.db` |
| `GUNICORN_WORKERS` | `1` |
| `GUNICORN_WORKER_CLASS` | `gevent` (default; `sync` for rollback) |
| `PUBLIC_BASE_URL` | `https://www.genesis-colonies.de` |
| `GC_EMBEDDED_CRON` | unset or `1` (default on in production) |
| `GC_EMBEDDED_CRON_SEC` | unset → `60` |
| `GC_EMBEDDED_BACKUP` | unset or `1` |
| `GC_EMBEDDED_BACKUP_KEEP` | unset → `7` |
| `GC_INTERNAL_CRON_TOKEN` | Optional but recommended for manual force HTTP cron |
| `GC_ALLOW_POSTGRES_PROD` | unset / `0` |
| Shop / Discord / SMTP / Vote | Live keys if features on |

Volume: mount **`/data`** on the **web** service only.

Disable embedded cron only if you intentionally use an external HTTP scheduler: `GC_EMBEDDED_CRON=0`.

### 4. CDN / Attack / Outbound IPs

- CDN: static `/static/*` only — never aggressive HTML/API cache
- Under Attack Mode: only during active floods
- Static Outbound IPs: only if a provider requires allowlisting

---

## Config-as-code (repo)

| File | Role |
|------|------|
| [`railway.toml`](../railway.toml) | Dockerfile, healthcheck, restart, watchPatterns |
| [`.dockerignore`](../.dockerignore) | Smaller build context |
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Smoke CI for Wait for CI |
| Entrypoint | Migrate + seed + gunicorn |
| `game/internal_cron.py` | Embedded maintenance + backup + HTTP cron |

---

## Postgres / scaling (later — not planned)

**Produktentscheidung:** Produktion bleibt auf **SQLite**. Siehe [CAPABILITY_STATUS.md](CAPABILITY_STATUS.md).

Optionaler PG-Code-Pfad existiert in [GC_PERF_CORE.md](GC_PERF_CORE.md), ist aber **kein Cutover-Ziel**. Until further notice: Replicas = 1, workers = 1.

**GC-PERF-PROD-002:** docker-entrypoint starts `scripts/run_maintenance_worker.py` by default (`GC_MAINTENANCE_WORKER=1`) and sets `GC_EMBEDDED_CRON=0` on gunicorn so Soft-On ticks do not share the web GIL. Opt out: `GC_MAINTENANCE_WORKER=0` (legacy in-process `[embedded-cron]`).

**GC-PERF-PROD-003:** With sidecar on, gunicorn `before_request` does **not** run global fleet tick / account-deletion piggyback (avoids SQLite writer races that freeze nav for up to `busy_timeout`).

**GC-RANK-CRON-001:** Sidecar uses a **respawn loop** + leader-lock **retry** so a deploy volume handoff (old container still holds `.gc_embedded_cron.lock`) cannot leave ranking/fleet without an owner. Admin → System → Runtime shows last ranking-worker run + dirty pending.

**GC-RANK-AUTO-001:** Runtime also shows a **maintenance bag heartbeat** (age + source). Auto ranking refreshes **all players' scores** every ~10 min, then rewrites ranks. Admin „Ranking jetzt neu berechnen“ = same full-universe reconcile on demand. If bag heartbeat is stale while Maintenance says Sidecar, check logs for `[maintenance-worker] started` / `waiting_for_leader_lock`.

After multi-writer DB (if ever): optional dedicated `scripts/run_game_worker.py` service + keep sidecar or HTTP cron.

Soft-Off A/B + `hold_ms` measurement: [GC_PERF_PROD_001.md](GC_PERF_PROD_001.md).

---

## Smoke after deploy

```bash
curl -sS https://www.genesis-colonies.de/healthz
curl -sS https://www.genesis-colonies.de/health
```

Expect `/healthz` → HTTP 200 `"status":"alive"` (cheap liveness; Docker HEALTHCHECK).  
Expect `/health` → HTTP 200 `"status":"ok"` (deep readiness; Railway deploy gate).  
Check Railway logs for `[maintenance-worker] started` (GC-PERF-PROD-002) or legacy `[embedded-cron] started`. Latency notes: [GC_PERF_PROD_001.md](GC_PERF_PROD_001.md).

---

## Related

- [CONTRIBUTING.md](CONTRIBUTING.md) — Production & CI
- [ARCHITECTURE.md](ARCHITECTURE.md) — HTTP cron / embedded bag
- [SECURITY.md](SECURITY.md) — `/health`
- [PAYMENT_SHOP.md](PAYMENT_SHOP.md) — `PUBLIC_BASE_URL`
- [CAPABILITY_STATUS.md](CAPABILITY_STATUS.md) — SQLite-first product path
- [GC_PERF_CORE.md](GC_PERF_CORE.md) — Performance / optional PG code path
