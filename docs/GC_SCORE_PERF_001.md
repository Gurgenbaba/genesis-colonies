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
| `dirty` | Ordinary cron / force | Bounded dirty batch (`GC_SCORE_DIRTY_BATCH`, default 50); ranks **once** after successes |
| `full` | `source=admin`, `full_reconcile=True`, or daily due (24h) | Full-universe safety net; clears all dirty |

Overlap guards: in-process `_RANKING_LOCK` + `runtime_state.ranking_worker_busy`.

## Phase 1 audit verdict (kept)

Finish recomputed **one player** (not all formulas). The bug was sync work inside the finish TX. Ranking route was already read-only.

## Env

| Env | Default | Meaning |
|-----|---------|---------|
| `GC_SCORE_DIRTY_BATCH` | 50 | Max dirty players per ordinary worker run |

## Tests

`tests/test_gc_score_perf_001_audit.py` plus updated ranking_worker / queue_engine / autoplay contracts.

## Ops

- Ranking UI may lag gameplay by up to ~10 minutes.
- Admin ranking recompute still runs **full** reconcile.
- Daily full reconcile repairs missed dirty marks without 10-minute full-universe cost.
