#!/bin/sh
# REPRO-004 production-topology entry (gunicorn gevent + optional maintenance sidecar).
set -eu

PORT="${PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-1}"
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"
MAINT="${GC_REPRO004_MAINT:-1}"

cd /app

echo "[REPRO-004] Installing dependencies..."
python -m pip install -q --disable-pip-version-check packaging gunicorn >/dev/null 2>&1 || true
python -m pip install -q --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || \
  python -m pip install -q --disable-pip-version-check Flask gevent gunicorn packaging python-dotenv >/dev/null 2>&1 || true

export GC_SKIP_MIGRATION_CHECK="${GC_SKIP_MIGRATION_CHECK:-1}"
export GC_MAINTENANCE_WORKER="${GC_MAINTENANCE_WORKER:-1}"
export GC_EMBEDDED_CRON="${GC_EMBEDDED_CRON:-0}"
export APP_ENV="${APP_ENV:-development}"
export GC_DB_BACKEND="${GC_DB_BACKEND:-sqlite}"

echo "[REPRO-004] Bootstrap verify GC_DB_PATH=${GC_DB_PATH}"
python -c "from game.bootstrap import bootstrap_application; bootstrap_application(skip_migration_check=True)"

if [ "$MAINT" = "1" ]; then
  echo "[REPRO-004] Starting maintenance sidecar supervisor..."
  (
    while true; do
      python scripts/run_maintenance_worker.py || true
      echo "[REPRO-004] maintenance worker exited; restart in 5s"
      sleep 5
    done
  ) &
  MAINT_PID=$!
  echo "[REPRO-004] maintenance supervisor pid=${MAINT_PID}"
else
  echo "[REPRO-004] Maintenance sidecar OFF (control run)"
fi

echo "[REPRO-004] Starting gunicorn workers=${WORKERS} worker_class=${WORKER_CLASS} port=${PORT}"
exec gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}" -b "0.0.0.0:${PORT}" \
  --timeout 120 --access-logfile - --error-logfile - --log-level info app:app
