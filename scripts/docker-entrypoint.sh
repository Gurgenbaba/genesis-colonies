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
try:
    from game.universe_news import ensure_changelog_seeded
    result = ensure_changelog_seeded()
    if result.get('seeded'):
        inserted = (result.get('import') or {}).get('inserted', 0)
        print(f'[GC] Timeline seeded from CHANGELOG ({inserted} major releases).')
    else:
        print(f'[GC] Timeline seed skipped ({result.get(\"reason\", \"ok\")}).')
finally:
    try:
        from game.db_pg import close_pool
        close_pool()
    except Exception:
        pass
"

echo "[GC] Verifying Codex catalog..."
python -c "
from game.config import init_config
init_config()
try:
    from game.codex import ensure_codex_catalog_ready
    result = ensure_codex_catalog_ready()
    if not result.get('ok'):
        raise SystemExit(f\"Codex catalog not ready: {result}\")
    print(f\"[GC] Codex catalog OK ({result.get('article_count')} articles, {result.get('category_count')} bands).\")
finally:
    try:
        from game.db_pg import close_pool
        close_pool()
    except Exception:
        pass
"

echo "[GC] Verifying Story TTS (edge-tts / Killian)..."
python -c "
from game.story.tts import resolve_voice, tts_available, tts_cache_dir
ok = tts_available()
print(f'[GC] Story TTS available={ok} voice={resolve_voice(\"de\")} cache={tts_cache_dir()}')
if not ok:
    print('[GC] WARNING: edge-tts missing — Story Ops will not have Killian neural voice.')
"

WORKERS="${GUNICORN_WORKERS:-1}"
# GC-PROD-SQLITE-STALL-001: HTTP availability must not depend on a single gevent
# event loop. Default to gthread so sync sqlite3 work cannot freeze /healthz.
# Galaxy live WS push is gevent/eventlet-only (see app.ws_long_lived_safe);
# under gthread the route refuses long-lived sockets and the client already
# degrades to existing galaxy polling — Availability > optional live push.
# Emergency rollback: GUNICORN_WORKER_CLASS=gevent (WS push returns) or sync.
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gthread}"
THREADS="${GUNICORN_THREADS:-4}"

# GC-PERF-PROD-002: run the maintenance bag in a sibling OS process so gunicorn
# does not share GIL/CPU with Soft-On autoplay/pirate ticks. Opt out with
# GC_MAINTENANCE_WORKER=0 (falls back to in-process embedded cron).
#
# Respawn loop: a one-shot background process that exits (crash, deploy lock
# race) would leave ranking/fleet with no owner because gunicorn has
# GC_EMBEDDED_CRON=0. Retry forever while the container is alive.
MAINT_WORKER="${GC_MAINTENANCE_WORKER:-1}"
if [ "${MAINT_WORKER}" = "1" ] || [ "${MAINT_WORKER}" = "true" ] || [ "${MAINT_WORKER}" = "yes" ] || [ "${MAINT_WORKER}" = "on" ]; then
  export GC_MAINTENANCE_WORKER=1
  export GC_EMBEDDED_CRON=0
  echo "[GC] Starting maintenance worker sidecar with respawn (GC-PERF-PROD-002)..."
  (
    while true; do
      python scripts/run_maintenance_worker.py || true
      echo "[GC] Maintenance worker exited; restarting in 5s..."
      sleep 5
    done
  ) &
  MAINT_PID=$!
  echo "[GC] Maintenance worker supervisor pid=${MAINT_PID}"
else
  echo "[GC] Maintenance sidecar off (GC_MAINTENANCE_WORKER=${MAINT_WORKER}); embedded cron may run in-process."
fi

GUNICORN_EXTRA=""
case "${WORKER_CLASS}" in
  gthread|sync)
    # Never fake gthread with threads=1 — that serializes like sync under load.
    if [ -z "${THREADS}" ] || [ "${THREADS}" -lt 2 ] 2>/dev/null; then
      THREADS=4
    fi
    GUNICORN_EXTRA="--threads ${THREADS}"
    ;;
esac

echo "[GC] Starting gunicorn on 0.0.0.0:${PORT} (workers=${WORKERS}, worker_class=${WORKER_CLASS}, threads=${THREADS})..."
# shellcheck disable=SC2086
exec gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}" ${GUNICORN_EXTRA} -b "0.0.0.0:${PORT}" --timeout 120 \
  --access-logfile - --error-logfile - --log-level info \
  app:app
