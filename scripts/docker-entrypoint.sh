#!/bin/sh
# Runs in the main container where Railway volumes are mounted (/data).
# preDeployCommand does NOT see volumes — migrations must run here before gunicorn.
set -e

PORT="${PORT:-5000}"

echo "[GC] Preparing SQLite path (GC_DB_PATH=${GC_DB_PATH:-<default>})..."
python -c "
from game.config import init_config
from game.db import ensure_db_parent_dir
init_config()
ensure_db_parent_dir()
"

echo "[GC] Applying migrations..."
python migrate.py

echo "[GC] Seeding player timeline from CHANGELOG if needed..."
python -c "
from game.config import init_config
init_config()
from game.universe_news import ensure_changelog_seeded
result = ensure_changelog_seeded()
if result.get('seeded'):
    inserted = (result.get('import') or {}).get('inserted', 0)
    print(f'[GC] Timeline seeded from CHANGELOG ({inserted} major releases).')
else:
    print(f'[GC] Timeline seed skipped ({result.get(\"reason\", \"ok\")}).')
"

WORKERS="${GUNICORN_WORKERS:-1}"
echo "[GC] Starting gunicorn on 0.0.0.0:${PORT} (workers=${WORKERS})..."
exec gunicorn -w "${WORKERS}" -b "0.0.0.0:${PORT}" --timeout 120 \
  --access-logfile - --error-logfile - --log-level info \
  app:app
