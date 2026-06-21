# State / AJAX System

Single live pipeline for the player UI (no full reload on game actions).

Siehe auch: [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md), [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md), [PLANET_SCOPE.md](PLANET_SCOPE.md), [ARCHITECTURE.md](ARCHITECTURE.md).

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

`GET /api/game-state` uses a **lightweight poll path** (`finish_source=game_state`) — HUD/timer only on the client (GC-803).

- `?include_panel=1` is for explicit action responses / legacy callers only — **not** used by normal client polling.
- Single SQLite connection per request
- No `buildings_panel`, full exchange/scrapyard panels, or teaser on diet polls
- Shell HUD on diet polls: `planet_limit`, `planets[]` (switcher), `active_planet` (+ `sidebar_nav`); no `research.techs[]`
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

- Poll: `GET /api/game-state` only — **HUD/timer path** (`applyHudOnlyGameState`, no `include_panel`)
- Page content: SSR on PJAX; mutations via `applyActionState()` full state
- Queue/timer completion: `reloadCurrentPage({ skipGameState: true })` — fresh SSR, no panel poll
- `patchShellHudFromState()` is the **only** DOM writer for the shell HUD
- Planet switch: POST → HUD patch → one PJAX reload → light poll resumes

## Kanonische Queue-Timer (Live-UI)

Verbindliche Regeln: [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) § *Kanonische Bauschleifen-Regel*.

| Rolle | Pflicht |
|-------|---------|
| **Server** | `finish_at`, `start_at`, `remaining_seconds` / `order_remaining` in game-state und Action-Responses; Unit-Aufträge als `amount × unit_time` |
| **Client** | `applyActionState()` / `applyGameStateData()` patchen Cards sofort; kein Frontend-Scheduling |
| **Aktiver Job** | Timer = Rest bis `finish_at` |
| **Wartender Job** | Timer = `finish_at − now` (Vorgänger + eigene Dauer), **nicht** nur `start_at − now` |
| **Monotonic DOM** | Nur bei gleichem `job_id` + gleichem `finish_at`; sonst Block ersetzen |

Implementierung: `game/queue_card.py` (`_apply_queued_wait_remaining`), `static/main.js` (`cardQueueTimerTarget`, `canPatchCardQueueInPlace`, `renderCardQueueBlock`).

---

`GET /upgrade/<type>` and `GET /research_start/<key>` still exist for no-JS fallback. With JS, clicks on `.btn-upgrade` / `.btn-research` are intercepted and use the POST APIs above.

## Tests

```bash
python -m pytest tests/test_game_state_live.py tests/test_effects.py tests/test_queue_engine.py -v
```
