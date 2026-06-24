"""
Background / cron queue tick runner for Genesis Colonies.

Bypasses request-level dedup (always calls finish_due_work directly).
Suitable for: cron, systemd timer, APScheduler, Celery, CLI.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .db import db
from .queue_engine import finish_due_work
from .runtime_state import record_queue_tick_result

logger = logging.getLogger(__name__)


def _empty_tick_result(source: str, scope: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "source": str(source or "cron"),
        "scope": str(scope or "due"),
        "finished": {
            "buildings": 0,
            "research": 0,
            "shipyard": 0,
            "defense": 0,
        },
        "affected_players": [],
        "affected_planets": [],
        "score_updates": 0,
        "rank_recalculated": False,
        "duration_ms": 0,
        "tick_elapsed_ms": 0,
        "errors": [],
        "batches": 0,
        "players_processed": 0,
        "skipped_due_to_dedup": False,
        "derived_sync_count": 0,
    }


def _merge_tick_results(target: Dict[str, Any], batch: Dict[str, Any]) -> None:
    fin = target["finished"]
    bfin = batch.get("finished") or {}
    for key in ("buildings", "research", "shipyard", "defense"):
        fin[key] = int(fin.get(key, 0)) + int(bfin.get(key, 0))

    target["score_updates"] = int(target.get("score_updates", 0)) + int(batch.get("score_updates", 0))
    target["rank_recalculated"] = bool(target.get("rank_recalculated")) or bool(batch.get("rank_recalculated"))

    players = set(target.get("affected_players") or [])
    players.update(batch.get("affected_players") or [])
    target["affected_players"] = sorted(players)

    planets = set(target.get("affected_planets") or [])
    planets.update(batch.get("affected_planets") or [])
    target["affected_planets"] = sorted(planets)

    target["errors"].extend(batch.get("errors") or [])
    if not batch.get("ok", True):
        target["ok"] = False

    target["duration_ms"] = int(target.get("duration_ms", 0)) + int(batch.get("duration_ms", 0))
    target["derived_sync_count"] = int(target.get("derived_sync_count", 0)) + int(
        batch.get("derived_sync_count", 0)
    )


def list_players_with_due_work(now: Optional[float] = None, conn=None) -> List[int]:
    """Distinct player ids with due build or research jobs."""
    own = conn is None
    if own:
        conn = db()
    if now is None:
        now = time.time()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT p.player_id AS player_id
            FROM build_queue b
            INNER JOIN planets p ON p.id = b.planet_id
            WHERE p.player_id IS NOT NULL AND b.finish_time <= ?
            UNION
            SELECT DISTINCT user_id AS player_id
            FROM research_queue
            WHERE finish_at <= ?;
            """,
            (float(now), float(now)),
        )
        return sorted({int(r["player_id"]) for r in cur.fetchall()})
    finally:
        if own and conn is not None:
            conn.close()


def run_tick(
    *,
    scope: str = "due",
    batch_size: int = 100,
    source: str = "cron",
    update_scores: bool = False,
    recalc_ranks: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """
    Process due queues globally in player batches (no request dedup).

    Args:
        scope: Currently only ``due`` (players with overdue jobs).
        batch_size: Max players per finish_due_work batch.
        source: Label for logs/audit (cron, worker, cli, …).
        persist: Write summary to runtime_state for admin health.
    """
    if scope != "due":
        raise ValueError(f"unsupported tick scope: {scope!r}")

    started = time.perf_counter()
    batch_size = max(1, int(batch_size))
    result = _empty_tick_result(source, scope)

    now = time.time()
    player_ids = list_players_with_due_work(now=now)
    result["players_processed"] = len(player_ids)

    logger.info(
        "queue tick start source=%s scope=%s players=%s batch_size=%s",
        source,
        scope,
        len(player_ids),
        batch_size,
    )

    if not player_ids:
        result["tick_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        result["duration_ms"] = result["tick_elapsed_ms"]
        if persist:
            record_queue_tick_result(result)
        return result

    for offset in range(0, len(player_ids), batch_size):
        batch_players = player_ids[offset : offset + batch_size]
        result["batches"] += 1
        for pid in batch_players:
            batch_result = finish_due_work(
                player_id=int(pid),
                now=now,
                source=str(source or "cron"),
                update_scores=update_scores,
                recalc_ranks=recalc_ranks,
            )
            _merge_tick_results(result, batch_result)

    result["tick_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    if result["duration_ms"] <= 0:
        result["duration_ms"] = result["tick_elapsed_ms"]

    logger.info(
        "queue tick done source=%s finished=%s players=%s batches=%s duration_ms=%s errors=%s",
        source,
        result.get("finished"),
        len(result.get("affected_players") or []),
        result.get("batches"),
        result.get("duration_ms"),
        len(result.get("errors") or []),
    )

    if persist:
        record_queue_tick_result(result)
    return result


def run_queue_tick(
    *,
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    source: str = "cron",
    update_scores: bool = False,
    recalc_ranks: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Single-scope tick (one player/planet or global). Back-compat wrapper."""
    started = time.perf_counter()
    logger.info(
        "queue tick start source=%s player_id=%s planet_id=%s",
        source,
        player_id,
        planet_id,
    )

    result = finish_due_work(
        player_id=player_id,
        planet_id=planet_id,
        source=str(source or "cron"),
        update_scores=update_scores,
        recalc_ranks=recalc_ranks,
    )

    result["tick_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    result["skipped_due_to_dedup"] = False
    result["scope"] = "scoped"
    result["batches"] = 1
    result["players_processed"] = 1 if player_id is not None else 0

    if persist:
        record_queue_tick_result(result)

    logger.info(
        "queue tick done source=%s finished=%s players=%s duration_ms=%s errors=%s",
        source,
        result.get("finished"),
        len(result.get("affected_players") or []),
        result.get("duration_ms"),
        len(result.get("errors") or []),
    )
    return result


def run_global_queue_tick(
    *,
    source: str = "cron",
    batch_size: int = 100,
    update_scores: bool = False,
    recalc_ranks: bool = False,
    persist: bool = True,
) -> Dict[str, Any]:
    """Finish due work for all players (batched). Prefer run_tick()."""
    return run_tick(
        scope="due",
        batch_size=batch_size,
        source=source,
        update_scores=update_scores,
        recalc_ranks=recalc_ranks,
        persist=persist,
    )


def _cli_main() -> int:
    import argparse
    import json
    import os
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Genesis Colonies queue tick")
    parser.add_argument("--scope", default="due", choices=["due"])
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--player-id", type=int, default=None)
    parser.add_argument("--planet-id", type=int, default=None)
    parser.add_argument("--source", default="cli")
    parser.add_argument("--scores", action="store_true", help="Legacy: recompute ranking scores (prefer run_ranking_worker.py)")
    parser.add_argument("--ranks", action="store_true", help="Legacy: recalc rank columns with --scores")
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    if args.player_id is not None or args.planet_id is not None:
        result = run_queue_tick(
            player_id=args.player_id,
            planet_id=args.planet_id,
            source=args.source,
            update_scores=bool(args.scores),
            recalc_ranks=bool(args.scores and args.ranks),
            persist=not args.no_persist,
        )
    else:
        result = run_tick(
            scope=args.scope,
            batch_size=args.batch_size,
            source=args.source,
            update_scores=bool(args.scores),
            recalc_ranks=bool(args.scores and args.ranks),
            persist=not args.no_persist,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_cli_main())
