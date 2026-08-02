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
| `POST /api/research/cancel` | Cancel research job → `{ ok, reason, state }` |
| `POST /api/shipyard/build` | Queue ships → `{ ok, state }` (+ optional `data` for page-local stocks/labels; GC-512D) |
| `POST /api/shipyard/queue/cancel` | Cancel shipyard job → `{ ok, state }` (+ optional `data`; GC-512D) |

Weitere `{ ok, state }` Mutationen: defense, exchange, inventory, vote, auction, planet APIs — siehe [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md). Shipyard mutations are **state-first** on the client: `applyActionState(res)` when `res.state` is present; `applyShipyardState(page, res.data)` only when `res.data` is present (stocks / card labels). Queue/HUD come from `state` via `patchShipyardPanelFromState` — no parallel shipyard-only envelope.

Actions use `_player_context_for_action()` (read-only DB) then **one** `refresh_player_live_state` inside `_build_game_state_payload` after the mutation.

## Poll vs. action payload

`GET /api/game-state` uses a **lightweight poll path** (`finish_source=game_state`) — HUD/timer only on the client (GC-803).

- `?include_panel=1` is for explicit action responses / legacy callers only — **not** used by normal client polling.
- Single SQLite connection per request
- No `buildings_panel`, full exchange/scrapyard panels, or teaser on diet polls
- Shell HUD on diet polls: `planet_limit`, `planets[]` (Planet Registry), `active_planet` (role/visual shell fields; `sidebar_nav` via SSR / full panel); no `research.techs[]`
- No `overview.status` (shipyard/fleet activity queries skipped)
- Inbox unread count read-only (`prepare=False`)
- Resource persist writes throttled (`GC_RESOURCE_PERSIST_SEC`, default ≥600 s since last planet update; GC-PERF-RES-001)
- Diet payload includes `poll_version` (HUD fingerprint); client diet polls send `?since=<poll_version>` and skip HUD apply on `{unchanged:true}` (**GC-PERF-LIVE-001**, server default on; `GC_STATE_DELTA=0` disables). Distinct from `state_version` (server clock, GC-557C).
- Busy-Poll (`intervalActive`): Build, Research, Shipyard, **Defense**, and **active fleets** — not only build/research/shipyard.
- Idle diet with matching `?since=` can return `{unchanged:true, diet_early_exit:1}` **before** `_build_game_state_payload` (**GC-PERF-STATE-004**). Due queue/fleet work always takes the full finish path. Fingerprint probe lives in `game.live_state.probe_poll_version`.
- Repeated idle polls may set `diet_probe_skip:1` when the process-local fingerprint still matches (**GC-PERF-STATE-005**) — skips EffectResolver/nav probe after unread check.
- Poll cadence (active/idle/hidden) is owned by `gameStatePollTick` only — unchanged polls must not `stopPolling`+`startPolling` (**GC-PERF-POLL-THRASH-001**).
- Client resource HUD climb uses `_resourceLive` + `production_per_hour` (not diet payload on every poll). After soft-nav / `skipGameState`, `bootstrapResourceLiveFromDom` restores rates from `GC.lastState` → `[data-res-rate]` → same-planet live rates (never force `0` alone). On `{unchanged:true}` with zero rates, client resyncs from `lastState` or forces one full diet (`resource_rates_missing`, cooldown) — resources stay off `poll_version` by design.
- **GC-INSTANT-HUD-RATES-001:** Full-page SSR writes production rates into `#resource-bar [data-res-rate]` via `HEADER_PROD_PER_HOUR` / `prod_per_hour` (`g.gc_prod_per_hour` from `_load_page_live_context`). GC-742 skip no longer leaves `/h` blank until the first diet poll.
- **GC-INSTANT-POLL-BOOT-001:** After SSR skip, `bootstrapBusyFlagsFromDom()` sets busy cadence; first diet poll waits the full active/idle interval (not a forced 3 s HUD wait). Notification poll stays deferred.
- **GC-INSTANT-QUEUE-FINISH-001:** At timer-zero, `optimisticDismissDueCardQueueBlock` patches the card level from `data-target-level` (server-provided next level) before `forceCanonicalGameStateRefresh` / `include_panel=1` reconciles. Landscape CSS is no-op when unchanged; `gc-perf-idle` ON is debounced to avoid chrome snap.
- **GC-PERF-OVERVIEW-TTFB-001:** Full-page `_load_page_live_context` stashes `g.gc_world_boss_count` / `g.gc_fleet_hud` on the same DB connection; `inject_globals` reuses them (no second WB/fleet connection on SSR).

Full panel payload is returned on **page load** and after **POST actions** (build, trade, fleet, …).

Production client intervals (override via `GC_POLL_*` env): active **5 s**, idle 12 s, hidden 30 s.
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
- Queue/timer completion: `GC.refreshGameState("timer_done"|"queue_timer_zero")` → `GET /api/game-state?include_panel=1` via `refreshPageAfterQueueEvent()` — **no PJAX full reload**
- `patchShellHudFromState()` is the **only** DOM writer for the shell HUD
- Planet switch: POST → `applyActionState(..., "planet_switch")` (HUD-only) → `reloadCurrentPage({ skipGameState, skipPolling, skipHydrate })` → poll restart

### State-cycle batching (GC-FLEET-NOTIFICATION-BATCH-001)

Mehrere Änderungen innerhalb **eines** State-Zyklus werden gemeinsam gepatcht:

| Regel | Pflicht |
|-------|---------|
| Fleet countdown zero | `requestMovementCountdownRefresh` debounce (150–300 ms) → höchstens ein `scheduleFleetStateRefresh` + ein `refreshGameState("fleet_countdown_expired")` |
| Fleet page list | `applyLiveState` → `renderActiveFleets` (Patch/Signatur); kein `initFleet()` erneut; Scroll erhalten |
| In-flight coalesce | Laufender Fleet-/Game-State-Request wird nicht dupliziert; weitere Gründe mergen |
| Notifications UI | Toast/Sound nach Kategorie bündeln; persistente `player_messages` bleiben einzeln |
| Dedupe | `latest_message_id` / `_lastToastedMessageId` — nicht nur `unread_count` |
| Payload | `notifications.new_items[]` (id, category, mission_type, …) — keine Message-Bodies im Diet-Poll |

`GET /api/notifications/summary` liefert denselben `notifications`-Slice. Kein paralleler Fleet-Poller.

## Kanonische Queue-Timer (Live-UI)

Verbindliche Regeln: [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) § *Kanonische Bauschleifen-Regel*.

| Rolle | Pflicht |
|-------|---------|
| **Server** | `finish_at`, `start_at`, `remaining_seconds` / `order_remaining` in game-state und Action-Responses; Unit-Aufträge als `ceil(amount / capacity) × unit_seconds` |
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
