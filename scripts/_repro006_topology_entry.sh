#!/bin/sh
# REPRO-006: gevent w1 + provenance hooks + optional sidecar.
set -eu

PORT="${PORT:-5000}"
WORKERS="${GUNICORN_WORKERS:-1}"
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"
THREADS="${GUNICORN_THREADS:-0}"
MAINT="${GC_REPRO_MAINT:-1}"

cd /app

export PYTHONPATH="/app/scripts/repro006_hooks:${PYTHONPATH:-}"
export GC_REPRO006_PROVENANCE="${GC_REPRO006_PROVENANCE:-1}"
export GC_REPRO006_PROV_LOG="${GC_REPRO006_PROV_LOG:-/data/tx_provenance.jsonl}"

echo "[REPRO-006] Installing dependencies..."
python -m pip install -q --disable-pip-version-check packaging gunicorn >/dev/null 2>&1 || true
python -m pip install -q --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || \
  python -m pip install -q --disable-pip-version-check Flask gevent gunicorn packaging python-dotenv flask-sock >/dev/null 2>&1 || true

export GC_SKIP_MIGRATION_CHECK="${GC_SKIP_MIGRATION_CHECK:-1}"
export GC_MAINTENANCE_WORKER="${GC_MAINTENANCE_WORKER:-1}"
export GC_EMBEDDED_CRON="${GC_EMBEDDED_CRON:-0}"
export APP_ENV="${APP_ENV:-development}"
export GC_DB_BACKEND="${GC_DB_BACKEND:-sqlite}"
export GC_GAME_WORKER_PRIMARY="${GC_GAME_WORKER_PRIMARY:-1}"

echo "[REPRO-006] Bootstrap GC_DB_PATH=${GC_DB_PATH}"
GC_REPRO006_PROCESS=bootstrap python -c "from game.bootstrap import bootstrap_application; bootstrap_application(skip_migration_check=True)"

# Truncate provenance log for this container run unless append requested
if [ "${GC_REPRO006_PROV_APPEND:-0}" != "1" ]; then
  : > "${GC_REPRO006_PROV_LOG}"
fi

if [ "${GC_REPRO_SIMULATE_QUEUE_TICK:-0}" = "1" ]; then
  echo "[REPRO-006] Simulating QUEUE_TICK_KEY heartbeat (not fleet/maint)..."
  (
    export GC_REPRO006_PROCESS=queue_tick_sim
    while true; do
      python - <<'PY'
import json, time
from game.runtime_state import QUEUE_TICK_KEY, set_runtime_value
set_runtime_value(
    QUEUE_TICK_KEY,
    json.dumps({
        "at": int(time.time()),
        "ok": True,
        "source": "repro_simulate",
        "scope": "due",
        "finished": {},
        "affected_players": [],
        "batches": 0,
        "players_processed": 0,
        "duration_ms": 0,
        "errors": [],
    }, ensure_ascii=False),
)
print("[REPRO-006] queue tick heartbeat stamped", flush=True)
PY
      sleep 10
    done
  ) &
fi

if [ "$MAINT" = "1" ]; then
  echo "[REPRO-006] Starting maintenance sidecar..."
  (
    export GC_REPRO006_PROCESS=maintenance_sidecar
    while true; do
      python scripts/run_maintenance_worker.py || true
      echo "[REPRO-006] maintenance exited; restart in 5s"
      sleep 5
    done
  ) &
  echo "[REPRO-006] maintenance supervisor pid=$!"
else
  echo "[REPRO-006] Maintenance OFF"
fi

EXTRA=""
if [ "$WORKER_CLASS" = "gthread" ]; then
  if [ -z "$THREADS" ] || [ "$THREADS" = "0" ] || [ "$THREADS" -lt 2 ] 2>/dev/null; then
    THREADS=4
  fi
  EXTRA="--threads ${THREADS}"
fi

export GC_REPRO006_PROCESS=gunicorn_web
echo "[REPRO-006] gunicorn workers=${WORKERS} class=${WORKER_CLASS} threads=${THREADS}"
# shellcheck disable=SC2086
exec gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}" ${EXTRA} -b "0.0.0.0:${PORT}" \
  --timeout 120 --access-logfile - --error-logfile - --log-level info app:app
