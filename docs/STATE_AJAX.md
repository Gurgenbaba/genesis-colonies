# State / AJAX System

Single live pipeline for the player UI (no full reload on game actions).

Siehe auch: [PLANET_SCOPE.md](PLANET_SCOPE.md) (Planetwechsel), [ARCHITECTURE.md](ARCHITECTURE.md) (Gesamtüberblick).

## Endpoints

| Route | Role |
|-------|------|
| `GET /api/game-state` | Canonical poll + page refresh payload |
| `GET /api/status` | Alias of `/api/game-state` (same JSON, same 401 shape) |
| `POST /api/buildings/upgrade` | Queue build → `{ ok, reason, state }` |
| `POST /api/buildings/cancel` | Cancel build job → `{ ok, reason, state }` |
| `POST /api/research/start` | Queue research → `{ ok, reason, state }` |
| `POST /api/research/cancel` | Cancel research job → `{ ok, reason, state } |

Actions use `_player_context_for_action()` (read-only DB) then **one** `refresh_player_live_state` inside `_build_game_state_payload` after the mutation.

## Poll vs. action payload

`GET /api/game-state` uses a **lightweight poll path** (`finish_source=game_state`):

- Single SQLite connection per request
- No `buildings_panel`, exchange/trader/scrapyard/teaser blocks
- No `overview.status` (shipyard/fleet activity queries skipped)
- Inbox unread count read-only (`prepare=False`)
- Resource persist writes throttled (≥120 s since last planet update)

Full panel payload is returned on **page load** and after **POST actions** (build, trade, fleet, …).

Production client intervals (override via `GC_POLL_*` env): active 8 s, idle 12 s, hidden 30 s.

## Server pipeline

```
_load_page_live_context(finish_source=…)
  → refresh_player_live_state()   # finish_due_work_once + derived sync
  → get_build_queue_status(skip_finish=True)
  → get_research_status(skip_finish=True)
  → mark_request_live_refreshed()
```

`coerce_skip_finish()` prevents a second finish if `update_planet_resources` or a prior refresh already ran in the same request.

## Frontend (`static/main.js`)

- Poll: `GET /api/game-state` only (not `/api/status`)
- `applyGameStateData()` patches shell resource bar, overview, buildings/research panels
- `applyActionState()` applies `json.state` and restarts polling
- PJAX: `cleanupPage()` → swap `#main-content` → `initPage({ force: true })` → `refreshGameState("page_init")`
- Chat: `GC.resumeChatPolling()` after PJAX (`static/js/chat.js`)

## Legacy full-page routes

`GET /upgrade/<type>` and `GET /research_start/<key>` still exist for no-JS fallback. With JS, clicks on `.btn-upgrade` / `.btn-research` are intercepted and use the POST APIs above.

## Tests

```bash
python -m pytest tests/test_game_state_live.py tests/test_effects.py tests/test_queue_engine.py -v
```
