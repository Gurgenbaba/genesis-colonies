# Railway Operator Guide — Genesis Colonies Production

Operator-only runbook for `www.genesis-colonies.de` (Railway service `genesis-colonies`).  
Not a public self-hosting guide. Code deploy path: [`railway.toml`](../railway.toml) + [`Dockerfile`](../Dockerfile) + [`scripts/docker-entrypoint.sh`](../scripts/docker-entrypoint.sh).

---

## Architecture constraints (do not override in UI)

| Setting | Required value | Why |
|---------|----------------|-----|
| Builder | Dockerfile (`railway.toml`) | Reproducible prod image |
| Healthcheck | `/health`, timeout 60s | Deploy gate |
| Start | Dockerfile `CMD` → entrypoint | Migrate-on-start needs volume |
| `preDeployCommand` | **Unset** | Pre-deploy container has **no** volume mount |
| Replicas | **1** | Volume + SQLite single-writer |
| Serverless / scale-to-zero | **Off** | Game + HTTP cron must stay warm |
| `GUNICORN_WORKERS` | **1** (SQLite) | Multi-worker only after Postgres cutover |
| Separate ranking worker service | **Do not create** | Volume is service-bound |

Migrations run in the main container on every start (`python migrate.py` in the entrypoint).

---

## Priority 1 — Railway UI / Ops checklist

Complete these in the Railway dashboard (and DNS registrar). Mark each item when verified.

### 1. DNS & domains

- [ ] `www.genesis-colonies.de` → Railway custom domain, port **8080** (or Railway-assigned `$PORT`), status healthy
- [ ] Apex `genesis-colonies.de` — finish registrar DNS (Railway shows **Waiting for DNS update** until records propagate). Prefer Railway-documented CNAME/ALIAS/ANAME for apex; avoid guessing bare A records
- [ ] Canonical public URL: **`PUBLIC_BASE_URL=https://www.genesis-colonies.de`** (PayPal webhooks, OAuth, emails). Keep apex as redirect-or-dual-host, but do not point live payment callbacks at an unresolved apex
- [ ] TLS certificates issued for both hosts once DNS is green

### 2. Wait for CI

- [ ] Railway service → **Wait for CI → Enable**
- [ ] GitHub branch protection: Required checks = **app CI / Railway**, **not** GitHub Pages (`pages build and deployment` / `deploy`)
- [ ] Prefer disabling GitHub Pages (Settings → Pages → Source: None) so Pages timeouts cannot confuse deploy status — see [CONTRIBUTING.md](CONTRIBUTING.md)

### 3. Environment variables (production)

Verify in Railway Variables (never commit secrets):

| Variable | Expected |
|----------|----------|
| `APP_ENV` / `FLASK_ENV` | `production` |
| `FLASK_DEBUG` | `0` |
| `SECRET_KEY` | Strong random (not `change-me-*`) |
| `GC_DB_BACKEND` | `sqlite` until intentional cutover |
| `GC_DB_PATH` | `/data/game.db` |
| `DATABASE_URL` | **Unset** or sqlite only — do **not** point at Postgres until cutover |
| `GC_ALLOW_POSTGRES_PROD` | Unset / `0` until cutover ticket |
| `GUNICORN_WORKERS` | `1` |
| `PUBLIC_BASE_URL` | `https://www.genesis-colonies.de` |
| `GC_INTERNAL_CRON_TOKEN` | Set; used by HTTP cron |
| Shop / Discord / SMTP / Vote keys | Live values if those features are on |

Volume: mount persistent volume at **`/data`** on the **web** service only.

Optional short perf window (then lower sample):

```env
GC_REQUEST_PERF_DEBUG=1
GC_REQUEST_PERF_SLOW_MS=500
GC_REQUEST_PERF_SAMPLE=1.0
```

### 4. HTTP cron + uptime

Ranking / fleet / vote piggyback on the **web** service (same SQLite file):

```http
POST https://www.genesis-colonies.de/api/internal/cron/ranking
Authorization: Bearer <GC_INTERNAL_CRON_TOKEN>
```

- [ ] External scheduler every **~10 minutes** (cron-job.org, UptimeRobot, or Railway Cron hitting the same POST)
- [ ] Optional `?force=1` only for manual recovery
- [ ] Separate **uptime** monitor on `GET https://www.genesis-colonies.de/health` (Railway healthcheck covers deploy only, not continuous uptime)

Do **not** run `scripts/run_ranking_worker.py` as a second Railway service on SQLite.

### 5. Backups

SQLite lives on the Railway volume — there is no automated in-repo backup.

- [ ] Periodic volume snapshot and/or copy of `/data/game.db` to off-platform storage
- [ ] Document restore: stop traffic → restore file → `python migrate.py` (entrypoint) → `/health` ok

Automated backups remain a roadmap item until Postgres cutover.

### 6. CDN Caching (Railway Edge) — cautious

App already serves `/static/` with cache-bust `?v=` (`GC_ASSET_VERSION` / `VERSION`) and strong Cache-Control when versioned.

If enabling Railway CDN:

- [ ] Cache **static assets** (`/static/*`) only
- [ ] **Do not** aggressively cache HTML, PJAX fragments, or `/api/*` (stale game state / auth)
- [ ] Prefer static-only; if HTML is cached at all, use a very short TTL or exclude it

### 7. Under Attack Mode / Static Outbound IPs

- **Under Attack Mode:** only during active DDoS/bot flood (browser challenge in front of login/API)
- **Static Outbound IPs:** only if Discord / PayPal / SMTP require IP allowlisting

---

## Config-as-code (repo)

| File | Role |
|------|------|
| [`railway.toml`](../railway.toml) | Dockerfile builder, healthcheck, restart, **watchPatterns** |
| [`.dockerignore`](../.dockerignore) | Smaller build context (tests/docs/.git excluded) |
| Entrypoint | Migrate + changelog seed + codex check + gunicorn |

Watch paths skip noise deploys (docs-only, `.cursor`, tests, etc.). App-relevant paths still trigger builds.

---

## Priority 3 — Postgres / scaling (later — not UI toggles)

Current production is **SQLite + volume + 1 worker**. Horizontal replicas and multi-worker are blocked until cutover.

Canonical path (see [GC_PERF_CORE.md](GC_PERF_CORE.md)):

1. **GC-PERF-PG-STAGING-001** — Railway staging + worker + smoke
2. **GC-PERF-PG-MIGRATE-001** — data import (already scripted; not live cutover)
3. **GC-PERF-PG-CUTOVER-001** — maintenance window, import, DNS/env switch, rollback drill
4. Set `GC_DB_BACKEND=postgres`, `DATABASE_URL=postgresql://…`, and only then `GC_ALLOW_POSTGRES_PROD=1`
5. Raise `GUNICORN_WORKERS` (>1); optional Redis; remove SQLite volume dependency → replicas become possible
6. Separate worker service only after shared Postgres (never share a SQLite file across services)

Until that epic lands: keep Replicas = 1 and workers = 1.

---

## Smoke after every deploy

```bash
curl -sS https://www.genesis-colonies.de/health
```

Expect HTTP 200 and `"status":"ok"`. Then spot-check login + one in-game page (Buildings or Overview).

---

## Related

- [CONTRIBUTING.md](CONTRIBUTING.md) — Production & CI, Pages vs Railway
- [ARCHITECTURE.md](ARCHITECTURE.md) — HTTP cron, request perf
- [SECURITY.md](SECURITY.md) — `/health` public surface
- [PAYMENT_SHOP.md](PAYMENT_SHOP.md) — `PUBLIC_BASE_URL` + PayPal webhooks
- [GC_PERF_CORE.md](GC_PERF_CORE.md) — Postgres staging / cutover
