# Genesis Colonies — Railway Deployment (SQLite + Volume)

Production on Railway uses **SQLite** on a **persistent Railway Volume**. PostgreSQL is **not implemented** yet (`GC_DB_BACKEND=postgres` fails at startup).

---

## Prerequisites

- GitHub repository connected to Railway
- Dockerfile build (configured via `railway.toml` in the repo root)
- **No** PostgreSQL service linked to the web service (remove or do not add until Phase 6)

---

## 1. Create the web service

1. Railway → **New Project** → **Deploy from GitHub repo**
2. Select this repository
3. Railway detects `railway.toml` and builds with the **Dockerfile**

---

## 2. Add a persistent volume

Without a volume, SQLite data is lost on every redeploy.

| Setting | Value |
|---------|--------|
| **Mount path** | `/data` |

Railway dashboard → your **web service** → **Volumes** → **Add Volume** → mount at `/data`.

---

## 3. Required environment variables

Set these on the **web service** (Variables tab):

| Variable | Value |
|----------|--------|
| `APP_ENV` | `production` |
| `FLASK_ENV` | `production` |
| `FLASK_DEBUG` | `0` |
| `SECRET_KEY` | Long random hex (see below) |
| `GC_DB_BACKEND` | `sqlite` |
| `GC_DB_PATH` | `/data/game.db` |

Generate `SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Do **not** use yet

| Variable / service | Reason |
|--------------------|--------|
| `DATABASE_URL` (PostgreSQL) | Backend not implemented; app ignores Postgres URLs |
| PostgreSQL plugin **linked** to web | Injects `DATABASE_URL`, causes confusion and extra cost |
| `GC_DB_BACKEND=postgres` | Fails bootstrap with a clear error |

If Railway injected `DATABASE_URL` from an old Postgres link, **delete that variable** or unlink the Postgres service.

---

## 4. Deploy flow

On each deploy:

1. **Build** — Docker image (`scripts/install.py` seeds schema in the image only; not used at runtime on Railway)
2. **Start** — `scripts/docker-entrypoint.sh` in the **main** container (where `/data` volume is mounted):
   - create DB parent directory
   - `python migrate.py` (idempotent; never wipes data)
   - Gunicorn on `0.0.0.0:$PORT`
3. **Healthcheck** — `GET /health`

**Do not use `preDeployCommand` for migrations.** Railway runs pre-deploy in a separate container **without** volume access — SQLite migrations there are lost and the app crashes.

---

## 5. Verify `/health`

Open:

```text
https://<your-service>.up.railway.app/health
```

Expected when healthy (HTTP **200**):

```json
{
  "status": "ok",
  "version": "1.5.x",
  "checks": {
    "database": { "ok": true, "backend": "sqlite", "path": "/data/game.db", "exists": true },
    "migrations": { "ok": true, "current": true, "pending": [] },
    "writable": { "ok": true },
    "config": { "ok": true, "production": true, "debug": false, "errors": [] }
  }
}
```

HTTP **503** / `"status": "fail"` — check deploy logs:

| Symptom | Fix |
|---------|-----|
| Pending migrations | Check deploy logs for `[GC] Applying migrations...`; run `python migrate.py` in Railway shell on the web service |
| `SECRET_KEY` errors | Set a strong unique `SECRET_KEY` |
| `Path not writable` | Volume mounted at `/data`; `GC_DB_PATH=/data/game.db` |
| Postgres / `GC_DB_BACKEND=postgres` | Set `GC_DB_BACKEND=sqlite` |

---

## 6. First admin user

After the first successful deploy, open a **Railway shell** on the web service:

```bash
python scripts/install.py --admin
```

Follow prompts to create an admin account. Change any default password immediately.

---

## 7. Local Docker (unchanged)

`docker compose` still uses port `5000` and volume `gc_data` → `/data/game.db`:

```bash
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
docker compose up --build -d
curl http://127.0.0.1:5000/health
```

---

## Railway deployment checklist

- [ ] GitHub repo connected; latest commit pushed (includes `railway.toml`, Dockerfile `PORT` bind)
- [ ] Volume mounted at **`/data`**
- [ ] Variables: `APP_ENV`, `FLASK_ENV`, `FLASK_DEBUG`, `SECRET_KEY`, `GC_DB_BACKEND=sqlite`, `GC_DB_PATH=/data/game.db`
- [ ] **No** PostgreSQL service linked to web
- [ ] **`DATABASE_URL`** unset (or not Postgres)
- [ ] Deploy succeeded; `/health` returns `"status": "ok"`
- [ ] Admin created via `python scripts/install.py --admin`
- [ ] Public URL / custom domain configured (optional)

---

## What Railway does **not** need in the repo

You do **not** commit `.env` or database files. Set secrets only in Railway Variables.

For troubleshooting shared with VPS/Docker, see [`DEPLOYMENT.md`](DEPLOYMENT.md).
