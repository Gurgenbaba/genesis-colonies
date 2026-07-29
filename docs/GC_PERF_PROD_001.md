# GC-PERF-PROD-001 — Production request latency root cause

> Owner: `game/health.py` · `game/live_state.py` · Flask hooks in `app.py`  
> Related: [GC_PERF_CORE.md](GC_PERF_CORE.md) · [RAILWAY_OPERATOR.md](RAILWAY_OPERATOR.md) · GC-2620

## Symptom

Unauthenticated production probes shared a ~2.5–4s floor:

| Path | ~ms (pre GC-2620 deploy) |
|------|--------------------------|
| `/health` | 2500 |
| `/login` | 4100 |
| `/ranking` (302) | 3800 |
| `/overview` (302) | 4100 |
| `/api/game-state` (401) | 4100 |

Even `/health` at multi-seconds rules out ranking SQL / `touch_player_online` as the sole cause.

## Ranked hypotheses

1. **Single gunicorn sync worker** (`GUNICORN_WORKERS` default 1) — requests serialize
2. **Heavy `/health` readiness** every 30s (Docker) + Railway deploy gate — DB×2, migration scan, 3 volume write probes
3. **Embedded cron in the same process** — GIL + SQLite write mutex + backup
4. Railway volume I/O / cold cache
5. Login template `get_game_settings()` DB open (login-only additive)

GC-2620 (roster 6) reduces autoplay pressure but does not remove (1)–(3).

## Slice shipped (prove bottleneck)

| Change | Purpose |
|--------|---------|
| `GET /healthz` | Cheap liveness (`ok`/`alive`) — no DB/FS |
| Docker `HEALTHCHECK` → `/healthz` | Stop monopolizing the sync worker every 30s |
| Railway `healthcheckPath=/health` | Keep deep readiness as deploy gate |
| `/health` `total_ms` + per-check `duration_ms` | Prove in-handler readiness cost |
| `[GC REQUEST PERF]` phases `before_request_ms` / `handler_ms` / `after_request_ms` | Split wall inside Flask |

## Proof protocol

Enable briefly on Railway:

```text
GC_REQUEST_PERF_DEBUG=1
GC_REQUEST_PERF_SLOW_MS=0
GC_REQUEST_PERF_SAMPLE=1.0
```

Then compare **client RTT** vs log `total_ms`:

| Observation | Meaning |
|-------------|---------|
| Client RTT ≫ log `total_ms` | Queue wait / edge / cold start **before** Flask |
| Client RTT ≈ `total_ms` and `/health` check `duration_ms` dominate | Heavy readiness / volume I/O |
| Spikes align with `[embedded-cron]` | Cron/GIL/DB lock coupling |
| `/healthz` client RTT still multi-second while `handler_ms` tiny | Confirms worker serialization / platform floor |

## Ops notes

- `GC_INACTIVE_AUTOPLAY_MAX_SESSIONS`: remove or set `6` (env `60` clamps to 12 after GC-2620)
- Next slices: move embedded cron off the web process, consider threads/workers after Postgres, auth/`touch_player_online` phase keys
- **GC-PERF-AUTOPLAY-001 (shipped):** inactive_autoplay stage no longer holds one SQLite IMMEDIATE across the full roster economy; short per-player commits + busy lease. Verify with Soft-Off A/B and Timekeeper boost on an active build queue. Check Railway `GC_POLL_ACTIVE_MS` if console shows game-state polling at 8000 ms (code default active is 5000).

## Smoke

```bash
curl -sS https://www.genesis-colonies.de/healthz
curl -sS https://www.genesis-colonies.de/health
```
