#!/bin/sh
# REPRO-005 worker-class topology entry (gunicorn + optional sidecar).
# Supports: gevent | gthread | sync via GUNICORN_WORKER_CLASS / GUNICORN_THREADS.
set -eu

PORT="${PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-1}"
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"
THREADS="${GUNICORN_THREADS:-0}"
MAINT="${GC_REPRO_MAINT:-0}"

cd /app

echo "[REPRO-005] Installing dependencies..."
python -m pip install -q --disable-pip-version-check packaging gunicorn >/dev/null 2>&1 || true
python -m pip install -q --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || \
  python -m pip install -q --disable-pip-version-check Flask gevent gunicorn packaging python-dotenv flask-sock >/dev/null 2>&1 || true

export GC_SKIP_MIGRATION_CHECK="${GC_SKIP_MIGRATION_CHECK:-1}"
export GC_MAINTENANCE_WORKER="${GC_MAINTENANCE_WORKER:-1}"
export GC_EMBEDDED_CRON="${GC_EMBEDDED_CRON:-0}"
export APP_ENV="${APP_ENV:-development}"
export GC_DB_BACKEND="${GC_DB_BACKEND:-sqlite}"

echo "[REPRO-005] Bootstrap verify GC_DB_PATH=${GC_DB_PATH}"
python -c "from game.bootstrap import bootstrap_application; bootstrap_application(skip_migration_check=True)"

if [ "$MAINT" = "1" ]; then
  echo "[REPRO-005] Starting maintenance sidecar supervisor..."
  (
    while true; do
      python scripts/run_maintenance_worker.py || true
      echo "[REPRO-005] maintenance worker exited; restart in 5s"
      sleep 5
    done
  ) &
  echo "[REPRO-005] maintenance supervisor pid=$!"
else
  echo "[REPRO-005] Maintenance sidecar OFF"
fi

EXTRA=""
if [ "$WORKER_CLASS" = "gthread" ] && [ "$THREADS" != "0" ]; then
  EXTRA="--threads ${THREADS}"
fi

echo "[REPRO-005] Starting gunicorn workers=${WORKERS} worker_class=${WORKER_CLASS} threads=${THREADS} port=${PORT}"
# shellcheck disable=SC2086
exec gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}" ${EXTRA} -b "0.0.0.0:${PORT}" \
  --timeout 120 --access-logfile - --error-logfile - --log-level info app:app
