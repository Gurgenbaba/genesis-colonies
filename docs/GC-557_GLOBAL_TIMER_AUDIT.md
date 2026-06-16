# GC-557 — Global Timer & Planet-Scope Audit

**Status:** GC-557A/B (timer core + fleet origin) — ongoing; split as needed.

## Problem

Timers drift or leak scope after planet switch, PJAX navigation, or fleet send — client sometimes reused stale duration math instead of server `finish_at` / `arrival_at`.

## Rules (canonical)

1. **Single timer source** — `remaining = serverTimestamp - now`; never re-derive duration client-side for queue/fleet timers.
2. **Planet scope** — build/shipyard/defense queues = context planet; research = account-wide; fleet movements = player-wide display, send origin = context planet.
3. **Planet switch** — stop ticker/poll, `_resetQueueLiveStates()`, refresh game-state, reload page shell.
4. **PJAX cleanup** — `GC.cleanupPage()` stops ticker, clears queue live cache, lifecycle timeouts.
5. **Zero seconds** — debounced `refreshGameState` / `refreshFleetState` / `requestMovementCountdownRefresh`.
6. **Debug** — `GC.debugPerf()` exposes timer/scope counters.

## Owner modules

| Area | Module |
|------|--------|
| Client ticker | `static/main.js` — `startProgressTicker`, `updatePageTimers`, `queueJobRemainingSeconds` |
| Server timestamps | `game/live_state.py`, `game/logic.py` — `server_time`, `countdown_at`, `finish_at` |
| Queue finish | `game/queue_engine.py` |
| Fleet timing | `game/fleet.py`, `game/fleet_calc.py` |

## Splits

- **GC-557A** — Queue live-state reset, planet-scope guards, PJAX cleanup
- **GC-557B** — Fleet origin + preview/send countdown sync
- **GC-557C** — Single time authority (`server_now`), `player_fleet_is_dirty`, origin audit, `GC.debugTimers()`

## Single time authority (GC-557C)

- Backend: `attach_canonical_server_time()` on `/api/game-state` and `fleet_ok()` responses
- Client: `GC.serverNow()` / `syncServerClockFromState()` — one perf-anchored clock; no `finish_at - Date.now()` for game timers
- Fleet poll: `player_fleet_is_dirty()` forces `process_fleet_tick` via `finish_player_due_work` before returning stale outbound state
- Debug: `GC.debugTimers()` in console — server/client drift, scope IDs, queue/fleet remainings, lifecycle counters
- Fleet POST audit: `game/fleet_origin.py` logs `Fleet Origin Scope Mismatch` when request/context/active/dom disagree

## GC-557D — DOM contract audit

Template/static contract tests in `tests/test_gc557d_timer_dom_audit.py`:

- Scoped pages (`buildings`, `research`, `shipyard`, `defense`, `fleet`, `trader-hub`, `logistics`) expose `data-planet-id`
- Queue partials + card macros use `data-timer-target`, `data-timer-kind`, `data-countdown-at`
- Fleet active legs + preview arrival use fleet timer contract + `data-server-remaining`
- Overview activities use `countdown_at` / `finish_at` from server
- No wall-clock math in expedition ETA or overview queue patches (`GC.serverNow()` only)

Run:

```bash
python -m pytest tests/test_gc557d_timer_dom_audit.py tests/test_gc557_global_timer_audit.py tests/test_gc557c_time_authority.py -v
```

## Tests

```bash
python -m pytest tests/test_gc557_global_timer_audit.py tests/test_static_live_updates.py -q
```
