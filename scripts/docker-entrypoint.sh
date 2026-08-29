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

echo "[GC] Verifying Codex catalog..."
python -c "
from game.config import init_config
init_config()
from game.codex import ensure_codex_catalog_ready
result = ensure_codex_catalog_ready()
if not result.get('ok'):
    raise SystemExit(f\"Codex catalog not ready: {result}\")
print(f\"[GC] Codex catalog OK ({result.get('article_count')} articles, {result.get('category_count')} bands).\")
"

echo "[GC] Verifying Story TTS (edge-tts / Killian)..."
python -c "
from game.story.tts import resolve_voice, tts_available, tts_cache_dir
ok = tts_available()
print(f'[GC] Story TTS available={ok} voice={resolve_voice(\"de\")} cache={tts_cache_dir()}')
if not ok:
    print('[GC] WARNING: edge-tts missing — Story Ops will not have Killian neural voice.')
"

# GC-PROD-AVAIL-001: keep a second web worker available while one worker is
# blocked in a synchronous SQLite wait. SQLite remains the single writer of
# record; this is HTTP availability headroom, not extra background workers.
WORKERS="${GUNICORN_WORKERS:-2}"
# GC-AST-LIVE: gevent worker class lets long-lived WS connections (galaxy
# live push) coexist with normal HTTP requests without pinning a worker slot
# per socket. Flip to "sync" for emergency rollback without a redeploy — the
# WS route/client both degrade gracefully (client falls back to polling).
WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"

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

echo "[GC] Starting gunicorn on 0.0.0.0:${PORT} (workers=${WORKERS}, worker_class=${WORKER_CLASS})..."
exec gunicorn -k "${WORKER_CLASS}" -w "${WORKERS}" -b "0.0.0.0:${PORT}" --timeout 120 \
  --access-logfile - --error-logfile - --log-level info \
  app:app
