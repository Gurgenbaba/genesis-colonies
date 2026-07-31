# GC-SCORE-PERF-001 — Deferred and batched score recomputation

> Status: **Phase 2–3 implemented (uncommitted)**  
> Owner: `game/score_events.py` (invalidate) · `game/ranking_worker.py` (batch) · formula unchanged in `game/ranking.py` / `resource_score.py`

## Design

### Hot path

```text
Finish-TX → gameplay mutate → mark player_score_dirty (version++) → commit
```

No `compute_player_scores`, no upsert snapshot, no rank rewrite inside queue/combat/autoplay/live finish.

### Dirty state (`player_score_dirty`)

| Column | Meaning |
|--------|---------|
| `player_id` | PK — one pending refresh per player |
| `dirty_version` | Generation; bumped on every mark |
| `dirty_since` | First mark timestamp (preserved on repeats) |
| `updated_at` | Last mark timestamp |

Compare-and-clear: worker deletes only when `dirty_version` still matches the version read for that batch item.

### Worker (sole batch owner)

Interval remains **600s** (`RANKING_WORKER_INTERVAL_SEC`).

| Mode | When | Behaviour |
|------|------|-----------|
| `full` | Every ordinary / forced cron tick | Full-universe score refresh for **all** players; ranks rewritten; dirty cleared |
| `dirty` | Direct helper / tests only (`process_dirty_score_batch`) | Bounded dirty batch (`GC_SCORE_DIRTY_BATCH`, default 50) |

Overlap guards: in-process `_RANKING_LOCK` + `runtime_state.ranking_worker_busy`.

## Ops

- Ranking UI refreshes for the whole universe every ~10 minutes.
- Admin ranking recompute still runs **full** reconcile.
- Dirty marks remain as a fast invalidate path between ticks.
