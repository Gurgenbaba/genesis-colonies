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

- Never auto-debit on poll or page load.
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

`POST /api/inventory/use` with `deposit_domain: "build"|"research"|"shipyard"` deposits **all** owned legacy time items for that domain into Timekeeper in one action (inventory Bau/Forschung/Werft chips).

## Migration

`migrations/098_timekeeper.sql`
