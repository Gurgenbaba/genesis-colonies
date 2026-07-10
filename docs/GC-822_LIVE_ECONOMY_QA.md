# GC-822 — Live Economy QA & Player Migration Check

Post **GC-820** (production) + **GC-821** (consumer rebalance) validation on **existing live saves**.

| Item | Owner |
|------|--------|
| Audit engine | `game/economy_live_audit.py` |
| CLI | `scripts/economy_live_audit.py` |
| Production | unchanged — `calculate_resource_output()` |

---

## Goal

Measure how the rework affects real player states. **No new formulas.** Fix bugs, document migration/compensation policy.

---

## What to check

| Area | Audit signal |
|------|----------------|
| Top players (high mines) | `max_mine_level`, production/day, upgrade pacing |
| Early game | `synthetic_profile_audit` L1–L10 |
| Storage fill | `storage_near_full`, `storage_overflow` |
| Build queues | `active_build_queue` |
| Trader | `exchange_limit_floor`, `low_trader_headroom` |
| Expeditions / loot | empire production drives rewards (auto via GC-820) |
| Military costs | fleet/defense defs GC-821D (+25 %) |
| Ranking | `ranking_score_rebase` — persistierte `player_scores` vs. live `compute_player_scores()` |

---

## Running the audit

```bash
# Top 25 players by mine level
python scripts/economy_live_audit.py --json

# Single player
python scripts/economy_live_audit.py --player-id 42 --json

# Endgame focus
python scripts/economy_live_audit.py --min-mine 60 --top 50 --json
```

Read-only — no DB mutations.

---

## Migration policy (default)

| Situation | Action |
|-----------|--------|
| Resource overflow before update | **Keep** — overflow rule unchanged |
| Running build queues | **Keep** — finish times valid; costs at queue start already spent |
| Storage > new cap | **No trim** — production caps growth only |
| Lower future upgrade costs (GC-821) | **Benefit** — no compensation clawback |
| Higher fleet/defense build costs | **Expected** — no retroactive charge |
| Ranking building score shift (GC-821) | **Expected** — cumulative power costs |
| Ranking score rebase (GC-SCORE) | **Expected** — einmalig Admin-Recompute nach Deploy |

**No mandatory compensation** unless audit flags systematic unfairness (support case-by-case).

---

## Risk flags

| Flag | Meaning |
|------|---------|
| `storage_overflow` | Balance > cap (allowed) |
| `storage_near_full` | ≥90 % fill — suggest storage/trader |
| `energy_starved` | `energy_ratio` < 0.85 |
| `exchange_limit_floor` | Daily limit = `exchange_daily_limit_min` |
| `active_build_queue` | Jobs in flight — verify after deploy |
| `high_mine_legacy_cost` | Mine ≥60 — benefited most from GC-821 cost curve |
| `ranking_score_rebase` | Persistierter `score_total` weicht ≥15 % von `compute_player_scores()` ab — Admin-Recompute |
| `low_trader_headroom` | Daily limit < 15 % of empire day production |

---

## GC-SCORE-G: ranking score rebase audit

Nach GC-SCORE-B/E/F können `player_scores`-Snapshots von der kanonischen Berechnung abweichen.

**Audit:** `ranking_score_rebase` vergleicht persistierte Zeile mit `compute_player_scores()` (±15 % auf `total_score`).

**Fix:** einmalig `POST /api/admin/ranking/recompute` (Admin → Ranking neu berechnen) oder Ranking-Cron.

---

## GC-822 code fix: ranking drift (historisch)

`compute_player_scores()` used legacy `BASE_COST × COST_FACTOR^level` while gameplay used GC-821 `power_upgrade_cost()`.

**Fix:** building investment sum via `cumulative_upgrade_resource_totals()` + `resource_score` (GC-SCORE-D).

Fleet/defense scores use `build_cost` via `resource_score` (GC-SCORE-C).

---

## Tests

```bash
python -m pytest tests/test_gc822_live_economy_audit.py tests/test_gc_score_g_ranking_rebase.py -v
```

---

## Deploy checklist

1. Run universe audit on staging DB snapshot from production
2. Review `flag_counts` — especially `storage_near_full`, `energy_starved`
3. Spot-check 3 profiles: early (mine ≤10), mid (~30), end (≥90)
4. Confirm `/api/game-state` production matches audit `production_per_hour`
5. After deploy: **Admin-Recompute** (`POST /api/admin/ranking/recompute`) — expect rank shifts from GC-SCORE rebase
6. Monitor support tickets 48 h — trader limits, storage, queue completion

---

## Forbidden

- Changing `calculate_resource_output()` or production exponents
- Mass resource grants without support ticket
- Trimming overflow stockpiles
