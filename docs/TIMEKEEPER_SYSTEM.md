# Timekeeper System (GC-TIMEKEEPER-001)

Single **Imperium time account** — empire-wide, manual apply only, separate from production % boosters.

## Owner

| Module | Responsibility |
|--------|----------------|
| `game/timekeeper.py` | Balance, credit/debit, apply, serialize |
| `game/inventory_use.py` | Legacy time items → `credit()` |
| `game/inventory.py` | Inventory vault + legacy deposit list (TK rail in Items vault) |
| `app.py` | `/api/timekeeper/apply`, game-state slice |
| `static/main.js` | HUD patch, one-click ⚡ apply (`mode: max`) |

## Rules

- Never auto-debit on poll or page load **for a human-driven request** (HUD/⚡ flow below).
- AI-only exception — `game/auto_empire.py::_auto_boost_timekeeper` may auto-credit + auto-apply for planner-driven AI paths such as pirate economy. **Dormant human Living Universe actions do not use this refill** and use canonical real queue timers.
- Apply only via **⚡** on the **active mini-queue strip** (Build/Research/Shipyard/Defense/Troops) or PE queue list → `/api/timekeeper/apply` with `mode: max` (server clamps to `min(balance, active_job_remaining)`).
- **One ⚡ per job** — no second Apply on building/research hero slots or PE tech cards.
- Domains: `build`, `research`, `shipyard`, `defense`, `troops`, `planet_research`, `ascension`.
- Shipyard/Defense/Troops: vor Debit `sync_*_queue_finish_times` (Batch-Restzeit); Kosten = Head-`finish_at − now`, nie `amount × unit_seconds`.
- Production boosters (`inventory_boosters`) unchanged; Shell boost chips only update when `state.active_boosters` is present (no stale cache on omit).

## Schema

- `timekeeper_balances` — `player_id`, `balance_sec`
- `timekeeper_transactions` — ledger (credit/debit audit)

## API

`POST /api/timekeeper/apply`

```json
{
  "domain": "build",
  "planet_id": 1,
  "mode": "partial|max|finish",
  "seconds": 1800
}
```

Response: `{ ok, reason, state, timekeeper, seconds_applied, jobs_finished }`

**GC-PERF-TK-002:** After a successful apply, `state.timekeeper` is forced from the apply ledger (`result.timekeeper`), not only from the post-commit state rebuild — so the HUD cannot keep a stale balance. Client prefers `res.timekeeper` over `state.timekeeper` and only calls `applyActionState` when `ok` and `seconds_applied > 0`. After JS changes, bump `VERSION` and hard-refresh so `main.js?v=…` cache busts.

**GC-PERF-TK-003:** Apply response uses slim action state (`include_panel=False`, `action_slim=True`) — HUD + queue slices only, no full `buildings_panel` / codex / shipyard catalog. Same diet pattern as GC-840 buildings upgrades. Logs `apply_ms` / `state_ms` on success.

**GC-PERF-TK-004:** For `domain=shipyard|defense|troops`, the slim apply response re-attaches a **queue-only** slice (`state.shipyard.queue` / `state.defense.queue` / `state.defense.troops`, no ship/defense catalogs) so the client can patch timers immediately. Without this, TK balance dropped but the mini-queue looked unchanged (false “click does nothing”). Client also refreshes `/api/shipyard` or `/api/defense` when on-page and the slice is missing, and merges prior production queues into `GC.lastState` on `timekeeper_apply`. Mini-queue `amount` / `target_amount` use **`amount_remaining`** (units still in the job), not original `amount_total`, so progressive TK delivery shrinks ×N immediately.

**GC-PERF-TK-020:** `timekeeper_apply` is a true partial state on the client: `commitGameStateCache()` merges the incoming slice onto the previous canonical cache and merges `research` nested state. Omitted unrelated HUD domains therefore keep their previous values; Shipyard/Defense queue preservation remains as defense-in-depth. This is the prerequisite for server-side Timekeeper response projection without creating a second state system.

**GC-PERF-TK-021:** A Timekeeper apply with an authoritative mutation snapshot uses a narrow server projection. Resources, build/research queues, initiation, notifications, fleet/attack alerts, account safety, score/commander and active-planet identity stay fresh. Unchanged Battle Pass/nav badges, Server Events/LiveOps, active-booster HUD, login rewards and planet-switcher/limit/relocation/Seed-Ark state are omitted and preserved by the GC-PERF-TK-020 client merge. A real queue completion still triggers the existing canonical panel reconcile.

**GC-PERF-TK-022:** Timekeeper partial responses also omit Commander and Score/Rank projection. A TK apply cannot mutate Commander state; a non-finishing boost cannot change score, and real queue completion already triggers the canonical include_panel reconcile. This removes several additional PostgreSQL reads from every apply without changing queue/resource/alert behavior.

**GC-PERF-TK-023:** Timekeeper partial responses also omit message notification, Command Initiation and account-safety HUD reads. A TK queue boost does not mutate those domains; GC-PERF-TK-020 preserves their cached values, and the dedicated notification heartbeat plus normal game-state polling remain authoritative for fresh alerts/safety state. Fleet HUD intentionally stays in the apply response until missing-fleet busy-state handling is hardened client-side.

**GC-PERF-TK-024:** The client now treats a missing Fleet slice in `timekeeper_apply` as truly unchanged. `syncActiveFleetBusyFromState()` preserves the previous busy flag when `active_fleets` is omitted, and `patchFleetHudFromActionPayload()` does not advance Fleet action-version state for a Fleet-neutral Timekeeper mutation. This is the safety prerequisite for omitting the expensive Fleet HUD projection from the server response.

**GC-PERF-TK-025:** Timekeeper partial responses now omit the full Fleet HUD projection. The apply click no longer rebuilds incoming-attack alerts, radar enrichment, active-fleet drawer payload or fleet-slot status. GC-PERF-TK-024 makes missing Fleet data neutral on the client, while the dedicated notification heartbeat and normal Fleet/game-state refresh remain authoritative. Queue/resource/Timekeeper slices stay immediate.

**GC-PERF-TK-026:** Role-based navigation is now partial-state safe: when a response contains neither `active_planet` identity nor a non-empty `planets[]` identity list, the sidebar resolver returns no update instead of fabricating the `general` role. This preserves the current sidebar for narrow Timekeeper responses and is the prerequisite for omitting Active-Planet identity construction server-side.

**GC-PERF-TK-027:** Timekeeper partial responses now omit the expensive `active_planet` identity/theme/sidebar construction. `active_planet_id` and `active_planet_name` remain in the response for queue/planet scope, while GC-PERF-TK-026 makes the missing identity slice a client no-op. Normal polls and planet-switch responses still build the full identity payload.

**GC-TK-SKIP-QUEUE-001:** After shipyard/defense **enqueue/cancel**, page `apply*State` must use `skipQueue: true` when `res.state` already patched the mini strip. A second paint from unenriched `data.queue` wiped ⚡ until reload. Empty `mini_queue_jobs: []` falls back to `queue[]`. Queue renders finalize TK buttons; silent rem/bal early-returns toast `timekeeper_apply_unavailable`. **Enqueue must not be treated as `completionReason`** (no async catalog refresh race). After stock paint, call `GC.finalizeTimekeeperQueueButtons(GC.lastState)`. `applyActionState` syncs `server_time` before queue/TK rem math.

**GC-TK-PANEL-REFRESH-001:** When apply completes the active head (`jobs_finished: true` on response + `state`, detected after finish by head-job id change), the client calls `forceCanonicalGameStateRefresh("timekeeper_apply")` on Buildings / Research / Shipyard / Defense / PE pages so locks, affordability, and stock update from `include_panel=1` (same path as timer-zero). Slim apply stays diet; full panel is only fetched after a real finish. **GC-INSTANT-QUEUE-FINISH-001:** natural timer-zero (and the same card path) optimistic-patches level from `data-target-level` before that reconcile so the UI does not wait on `include_panel` RTT. `syncProductionPanelsAfterGameState` also refreshes shipyard/defense **catalog/stock** after any on-page `timekeeper_apply` when the slim slice omitted ships/defenses — progressive batch delivery can grant units without `jobs_finished`.
`POST /api/inventory/use` with `deposit_domain: "build"|"research"|"shipyard"|"all"` deposits **all** owned legacy time items for that domain (or every depositable domain when `"all"`) into Timekeeper in one action (inventory vault TK chips: Alle / Bau / Forschung / Werft).

## AI planner auto-boost (GC-2616)

The shared planner still supports an **AI-only** Shipyard/Defense acceleration path:

1. After a planner-driven `try_build_defense`/`try_build_ships` enqueue, an AI caller may run `_auto_boost_timekeeper(conn, player_id, planet_id, domain)`.
2. If its Timekeeper balance is empty, the helper can credit 36,000 s with source `autoplay_replenish`.
3. It then applies that balance through the canonical Timekeeper owner.

Living Universe V6 dormant-human decisions intentionally bypass this helper for
Shipyard/Defense and pass `duration_cap=None` for Build/Research. A dormant
human therefore gets no synthetic queue time or synthetic Timekeeper credit.

## Migration

`migrations/098_timekeeper.sql`
