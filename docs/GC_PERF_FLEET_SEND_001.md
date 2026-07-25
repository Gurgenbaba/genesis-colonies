# GC-PERF-FLEET-SEND-001 — Instant Fleet Dispatch

> Status: ✅  
> Epic: EPIC-19 Performance Core · [GC_PERF_CORE.md](GC_PERF_CORE.md)  
> Owner: `app.py` (send/recall response), `static/main.js` (critical path), diet via `game/live_state.apply_action_state_diet`

---

## Problem

`POST /api/fleet/send` felt slow: after a fast write (`send_fleet`), the response waited on a full `include_panel` game-state rebuild (`finish_player_due_work` + buildings/defense/shipyard panels). The fleet page then `await refreshFleetState` and `syncFleetUiAfterMutation({ immediate: true })` hit `/api/fleet/state` again.

## Fix

1. **Slim mutation state** — `api_fleet_send` / `api_fleet_recall` use `_fleet_mutation_game_state` → `include_panel=False` + `action_slim=True`.
2. **No finish on response** — finish sources in `_FLEET_MUTATION_LIVE_SOURCES` use poll live path (`read_player_live_state_for_poll`); write already deducted ships/fuel.
3. **Skip before_request global tick** for `api_fleet_send` / `api_fleet_recall`.
4. **Client** — success patches from live payload + `applyActionState`; no `await refreshFleetState` on critical path; `fleet_send_success` → deferred coalesce only.

## Instant UX contract

| Layer | Source of truth on click |
|-------|--------------------------|
| Hangar / resources / slots | `data.updated_*` / `active_slots` |
| Active list + HUD | `data.fleet` + `mergeFleetMovementIntoHud` |
| HUD/resources shell | slim `state` via `applyActionState` |
| Full fleet page reconcile | deferred `scheduleFleetStateRefresh` (not awaited) |

## Tests

`tests/test_gc_perf_fleet_send_001.py`

## Related

- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — send/recall response diet
- Buildings diet pattern: GC-840 / `_uses_action_state_diet`
