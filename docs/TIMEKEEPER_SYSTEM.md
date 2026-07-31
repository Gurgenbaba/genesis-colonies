# Timekeeper System (GC-TIMEKEEPER-001)

Single **Imperium time account** — empire-wide, manual apply only, separate from production % boosters.

## Owner

| Module | Responsibility |
|--------|----------------|
| `game/timekeeper.py` | Balance, credit/debit, apply, serialize |
| `game/inventory_use.py` | Legacy time items → `credit()` |
| `game/inventory.py` | Inventory hero + legacy deposit list |
| `app.py` | `/api/timekeeper/apply`, game-state slice |
| `static/main.js` | HUD patch, one-click ⚡ apply (`mode: max`) |

## Rules

- Never auto-debit on poll or page load **for a human-driven request** (HUD/⚡ flow below).
- Exception — autoplay accounts (EPIC-26, GC-2616): `game/auto_empire.py::_auto_boost_timekeeper` auto-credits + auto-applies for **inactive sticky-roster** accounts (`game/inactive_autoplay.py`) and **pirate AI bots** (`game/pirates/economy.py`) only, never for a human player mid-session. Both share the one `plan_passive_planet_tick` owner — no parallel speed mechanic per faction (Rule 16).
- Apply only via **⚡** on the **active mini-queue strip** (Build/Research/Shipyard/Defense) or PE queue list → `/api/timekeeper/apply` with `mode: max` (server clamps to `min(balance, active_job_remaining)`).
- **One ⚡ per job** — no second Apply on building/research hero slots or PE tech cards.
- Domains: `build`, `research`, `shipyard`, `defense`, `planet_research`, `ascension`.
- Shipyard/Defense: vor Debit `sync_*_queue_finish_times` (Batch-Restzeit); Kosten = Head-`finish_at − now`, nie `amount × unit_seconds`.
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

Response: `{ ok, reason, state, timekeeper, seconds_applied }`

**GC-PERF-TK-002:** After a successful apply, `state.timekeeper` is forced from the apply ledger (`result.timekeeper`), not only from the post-commit state rebuild — so the HUD cannot keep a stale balance. Client prefers `res.timekeeper` over `state.timekeeper` and only calls `applyActionState` when `ok` and `seconds_applied > 0`. After JS changes, bump `VERSION` and hard-refresh so `main.js?v=…` cache busts.

**GC-PERF-TK-003:** Apply response uses slim action state (`include_panel=False`, `action_slim=True`) — HUD + queue slices only, no full `buildings_panel` / codex / shipyard catalog. Same diet pattern as GC-840 buildings upgrades. Logs `apply_ms` / `state_ms` on success.

**GC-PERF-TK-004:** For `domain=shipyard|defense`, the slim apply response re-attaches a **queue-only** slice (`state.shipyard.queue` / `state.defense.queue`, no ship/defense catalogs) so the client can patch timers immediately. Without this, TK balance dropped but the mini-queue looked unchanged (false “click does nothing”). Client also refreshes `/api/shipyard` or `/api/defense` when on-page and the slice is missing, and merges prior production queues into `GC.lastState` on `timekeeper_apply`.

`POST /api/inventory/use` with `deposit_domain: "build"|"research"|"shipyard"|"all"` deposits **all** owned legacy time items for that domain (or every depositable domain when `"all"`) into Timekeeper in one action (inventory Alle / Bau / Forschung / Werft chips).

## Autoplay auto-boost (GC-2616)

Defense/Shipyard queues have no `duration_cap` in `plan_passive_planet_tick` (build/research already force-complete same-tick via `duration_cap` + `chain_limit`, so an auto-apply there would spend balance with no visible extra effect). For autoplay accounts only:

1. After a successful `try_build_defense`/`try_build_ships` enqueue, `_auto_boost_timekeeper(conn, player_id, planet_id, domain)` runs.
2. If `timekeeper.get_balance(player_id) <= 0`: `timekeeper.credit(player_id, 36_000, source="autoplay_replenish")` (10h refill).
3. `timekeeper.apply_timekeeper(player_id, domain, planet_id=planet_id, mode="max")` — same ledger/API path a manually playing owner uses; if the account's human owner returns to active play, their own Timekeeper history shows these entries (`source="autoplay_replenish"` / `source` starting with `apply:<domain>`) — nothing hidden or fake.

## Migration

`migrations/098_timekeeper.sql`
