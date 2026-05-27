# Genesis Colonies — Deployment

Reproducible installation for local development, Linux VPS, and Docker.

---

## Quick install (any OS)

```bash
python scripts/install.py --venv --admin
```

Windows PowerShell:

```powershell
py -3 scripts\install.py --venv --admin
```

This will:

1. Check Python 3.10+
2. Create `.venv` (optional)
3. Install `requirements.txt`
4. Copy `.env.example` → `.env` if missing
5. Run `init_db` + `migrate.py`
6. Verify write permissions and migrations
7. Optionally create an admin user

---

## Environment variables

Copy `.env.example` to `.env` and edit:

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | **Yes (prod)** | Session signing key — random hex, never default |
| `APP_ENV` | Prod | `production` or `development` |
| `FLASK_DEBUG` | Prod | Must be `0` in production |
| `GC_DB_BACKEND` | No | `sqlite` (default) |
| `GC_DB_PATH` | No | SQLite file path (default `game/game.db`) |
| `DATABASE_URL` | Alt | `sqlite:///game/game.db` mapped to `GC_DB_PATH` |
| `HOST` / `PORT` | No | Dev server bind (default `127.0.0.1:5000`) |
| `REDIS_URL` | Future | Optional cache/sessions |
| `MAIL_*` | Future | Optional SMTP |

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Windows (local)

```powershell
cd "C:\path\to\Genesis Colonies"
py -3 scripts\install.py --venv --admin
.\.venv\Scripts\Activate.ps1
python app.py
```

Open: http://127.0.0.1:5000/health

---

## Linux VPS (systemd + gunicorn)

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
git clone <repo-url> /opt/genesis-colonies
cd /opt/genesis-colonies

python3 scripts/install.py --venv --admin
cp .env.example .env
nano .env   # SECRET_KEY, APP_ENV=production, FLASK_DEBUG=0

source .venv/bin/activate
pip install -r requirements-prod.txt

# Test
gunicorn -w 2 -b 127.0.0.1:5000 app:app
curl -s http://127.0.0.1:5000/health | python -m json.tool
```

Example systemd unit `/etc/systemd/system/genesis-colonies.service`:

```ini
[Unit]
Description=Genesis Colonies
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/genesis-colonies
EnvironmentFile=/opt/genesis-colonies/.env
ExecStart=/opt/genesis-colonies/.venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 120 app:app
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Put nginx/Caddy in front for TLS.

---

## Docker

```bash
# Set secret in shell or .env next to compose file
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

docker compose up --build -d
curl http://127.0.0.1:5000/health
```

Data persists in Docker volume `gc_data` (`GC_DB_PATH=/data/game.db`).

**Important:** Override `SECRET_KEY` at runtime — do not use the example key from the image.

---

## Railway (SQLite + Volume)

PostgreSQL is **not** implemented yet. Use SQLite on a Railway Volume mounted at `/data` with `GC_DB_PATH=/data/game.db`. Do not link a PostgreSQL service or rely on `DATABASE_URL`.

Full guide: [`DEPLOY_RAILWAY.md`](DEPLOY_RAILWAY.md).

Migrations run in `scripts/docker-entrypoint.sh` at container start (not `preDeployCommand` — volumes are unavailable there).

---

## Update existing installation

```bash
git pull
source .venv/bin/activate   # or .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python migrate.py
# restart app / docker compose restart
curl -s http://127.0.0.1:5000/health
```

If `/health` returns `503` with pending migrations, run `python migrate.py` again.

---

## Health check

`GET /health` returns JSON:

```json
{
  "status": "ok",
  "version": "1.5.0",
  "checks": {
    "database": {"ok": true},
    "migrations": {"ok": true, "pending": []},
    "writable": {"ok": true},
    "config": {"ok": true, "production": true, "debug": false}
  }
}
```

- `200` — healthy
- `503` — database, migrations, permissions, or production config failed

---

## Safety rules

| Rule | Behavior |
|------|----------|
| Insecure `SECRET_KEY` in production | App exits on bootstrap |
| `FLASK_DEBUG=1` in production | App exits on `python app.py` |
| Pending migrations in production | App exits on bootstrap |
| Pending migrations in development | Warning only |

Skip migration guard (CI/tests only): `GC_SKIP_MIGRATION_CHECK=1`

---

## Operator checklist

- [ ] `.env` exists with unique `SECRET_KEY`
- [ ] `APP_ENV=production`, `FLASK_DEBUG=0`
- [ ] `python scripts/install.py` or `python migrate.py` completed
- [ ] `/health` returns `"status": "ok"`
- [ ] Reverse proxy + TLS configured
- [ ] `game/game.db` (or `GC_DB_PATH`) backed up regularly
- [ ] Default admin password changed if used

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Pending database migrations` | `python migrate.py` |
| `SECRET_KEY is an insecure default` | Set strong key in `.env` |
| `Path not writable` | Fix permissions on `game/` directory |
| Health 503 migrations | Run migrate, verify `migration_history` table |
