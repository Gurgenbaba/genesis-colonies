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

## Ops Soft-Off A/B (slowdown / Timekeeper / Lock Storm)

When navigation, Timekeeper, or fleet arrivals feel stuck — or logs show
`database is locked` on `process_fleet_tick` / `touch_player_online`:

1. Admin → LiveOps → **Inactive Autoplay Soft-Off** (or env `GC_INACTIVE_AUTOPLAY_ENABLED=0`) → wait ~1 min → navigate `/overview`↔`/ranking` + Timekeeper + one fleet arrival (2–3 min).
2. If still slow/locked: Soft-Off **Pirates AI** → same checks.
3. Interpret:
   - Autoplay off alone fixes → autoplay tick cost / short-TX chatter
   - Pirates off fixes → pirate economy (check `hold_ms` / `write_commits`)
   - Both off still locked → fleet mega-TX / worker (see GC-PERF-LOCK-001)

**Measure in Railway logs before shipping further “perf” commits:**

```text
post-maint stage=inactive_autoplay hold_ms=… manage_tx=0
post-maint stage=pirates hold_ms=… manage_tx=0
inactive_autoplay … hold_ms=… write_commits=…
pirates … hold_ms=… write_commits=…
[maintenance-worker] started   ← GC-PERF-PROD-002 sidecar (preferred)
[embedded-cron] started        ← legacy in-process (only if GC_MAINTENANCE_WORKER=0)
```

Optional request wall: `GC_REQUEST_PERF_DEBUG=1`, `GC_REQUEST_PERF_SLOW_MS=0`, `GC_REQUEST_PERF_SAMPLE=1.0`.

## Ops notes

- `GC_INACTIVE_AUTOPLAY_MAX_SESSIONS`: remove or set `6` (env `60` clamps to 12 after GC-2620)
- **GC-PERF-AUTOPLAY-001 / GC-PERF-TK-001 (shipped):** autoplay + pirates stages use short write TXs (`manage_tx=False`) + busy leases; shipyard/defense Timekeeper also shifts `started_at`
- **GC-PERF-TK-002:** `/api/timekeeper/apply` forces `state.timekeeper` from the apply ledger after commit; client prefers top-level `timekeeper` and clears monotonic `serverRemaining` before patch; bump `VERSION` + hard-refresh after deploy so `main.js` cache updates
- **GC-PERF-TK-003:** `/api/timekeeper/apply` returns slim action state (no full panel/codex) — cuts 2–3s live-boost latency from fat payload rebuild; logs `apply_ms`/`state_ms`
- **GC-PERF-BOOST-001:** production boosters tier-stack additively across source items (25+50 → +75%); same item extends duration; HUD chip shows combined %; inventory lists each tier; non-production timed boosters still use max
- **GC-PERF-LOCK-001:** fleet worker no longer holds one `BEGIN IMMEDIATE` across all due movements — `process_fleet_tick(..., manage_transaction=True)` commits per movement; `touch_player_online` swallows SQLITE_BUSY and always attempts roster release; `PRAGMA busy_timeout=20000`
- **GC-PERF-AUTOPLAY-002:** sticky roster defaults to `tick_per_cron=1`, `chain_limit=2`, 50ms yield between short-TX economies, 800ms tick budget (`budget_stopped`); Soft-On stays recommended
- **GC-PERF-IMG-001…004:** compressed shell/card images (frame.webp ≤120KB, expedition.webp, landscapes, cards); WebP primary in galaxy/JS/catalog; Overview frame preload + `?v=` cache bust
- **GC-PERF-PROD-002 (shipped):** docker-entrypoint starts `scripts/run_maintenance_worker.py` by default (`GC_MAINTENANCE_WORKER=1`) and forces `GC_EMBEDDED_CRON=0` on gunicorn — maintenance bag no longer shares the web process GIL. Opt out with `GC_MAINTENANCE_WORKER=0`
- **GC-RANK-CRON-001:** sidecar respawn + leader-lock retry so deploy handoff cannot kill automatic ranking; Admin Runtime shows ranking-worker last run
- Check Railway `GC_POLL_ACTIVE_MS` if console shows game-state polling at 8000 ms (code default active is 5000)

## Smoke

```bash
curl -sS https://www.genesis-colonies.de/healthz
curl -sS https://www.genesis-colonies.de/health
```

Expect `/healthz` → HTTP 200 `"status":"alive"` (cheap liveness; Docker HEALTHCHECK).  
Expect `/health` → HTTP 200 `"status":"ok"` (deep readiness; Railway deploy gate).  
Check Railway logs for `[maintenance-worker] started` (or legacy `[embedded-cron] started` if sidecar off).
