"""
Background / cron queue tick runner for Genesis Colonies.

Bypasses request-level dedup (always calls finish_due_work directly).
Suitable for: cron, systemd timer, APScheduler, Celery, CLI.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from .db import db, table_exists
from .queue_engine import finish_due_work
from .runtime_state import record_queue_tick_result

logger = logging.getLogger(__name__)

_FINISHED_KEYS = (
    "buildings",
    "research",
    "planet_research",
    "ascension",
    "shipyard",
    "defense",
    "troops",
    "fleet_arrivals",
    "fleet_returns",
    "fleet_holding",
    "planet_relocations",
)


def _empty_tick_result(source: str, scope: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "source": str(source or "cron"),
        "scope": str(scope or "due"),
        "finished": {key: 0 for key in _FINISHED_KEYS} | {"inbox_purged": 0},
        "affected_players": [],
        "affected_planets": [],
        "score_updates": 0,
        "rank_recalculated": False,
        "duration_ms": 0,
        "tick_elapsed_ms": 0,
        "errors": [],
        "batches": 0,
        "players_processed": 0,
        "planet_scopes_processed": 0,
        "account_scopes_processed": 0,
        "skipped_due_to_dedup": False,
        "derived_sync_count": 0,
        "skipped_locked_planets": [],
    }


def _merge_tick_results(target: Dict[str, Any], batch: Dict[str, Any]) -> None:
    fin = target["finished"]
    bfin = batch.get("finished") or {}
    for key in _FINISHED_KEYS:
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
    locked = set(int(pid) for pid in (target.get("skipped_locked_planets") or []))
    locked.update(int(pid) for pid in (batch.get("skipped_locked_planets") or []))
    target["skipped_locked_planets"] = sorted(locked)


def list_due_work_scopes(
    now: Optional[float] = None,
    conn=None,
) -> Dict[int, Dict[str, Any]]:
    """Exact player/planet scopes containing due server-owned queue work.

    GC-PERF-QUEUE-WORKER-001: the former worker candidate query only saw
    build_queue + research_queue. Shipyard/defense/Planet-Evolution/troop jobs
    therefore still became due inside `/api/game-state` and forced the HTTP
    request to finish them synchronously. Build the candidate UNION from tables
    that actually exist so legacy/test schemas stay compatible.

    GC-PERF-QUEUE-SCOPE-001: retain the due planet instead of collapsing the
    scan to player IDs. The queue-only worker can then finish only those planets
    and avoid probing every empty queue family on every colony. Account research
    remains an explicit player-scoped flag.
    """
    own = conn is None
    if own:
        conn = db()
    ts = float(now if now is not None else time.time())
    try:
        selects: list[str] = [
            """
            SELECT p.player_id AS player_id, b.planet_id AS planet_id, 0 AS account_scope
            FROM build_queue b
            INNER JOIN planets p ON p.id = b.planet_id
            WHERE p.player_id IS NOT NULL AND b.finish_time <= ?
            """,
            """
            SELECT user_id AS player_id, NULL AS planet_id, 1 AS account_scope
            FROM research_queue
            WHERE user_id IS NOT NULL AND finish_at <= ?
            """,
        ]
        params: list[float] = [ts, ts]

        optional = (
            (
                "planet_research_queue",
                """
                SELECT p.player_id AS player_id, q.planet_id AS planet_id, 0 AS account_scope
                FROM planet_research_queue q
                INNER JOIN planets p ON p.id = q.planet_id
                WHERE p.player_id IS NOT NULL AND q.finish_at <= ?
                """,
            ),
            (
                "planet_ascension_queue",
                """
                SELECT p.player_id AS player_id, q.planet_id AS planet_id, 0 AS account_scope
                FROM planet_ascension_queue q
                INNER JOIN planets p ON p.id = q.planet_id
                WHERE p.player_id IS NOT NULL AND q.state = 'active' AND q.finish_at <= ?
                """,
            ),
            (
                "shipyard_queue",
                """
                SELECT p.player_id AS player_id, q.planet_id AS planet_id, 0 AS account_scope
                FROM shipyard_queue q
                INNER JOIN planets p ON p.id = q.planet_id
                WHERE p.player_id IS NOT NULL AND q.status = 'queued' AND q.finish_at <= ?
                """,
            ),
            (
                "defense_queue",
                """
                SELECT p.player_id AS player_id, q.planet_id AS planet_id, 0 AS account_scope
                FROM defense_queue q
                INNER JOIN planets p ON p.id = q.planet_id
                WHERE p.player_id IS NOT NULL AND q.status = 'queued' AND q.finish_at <= ?
                """,
            ),
            (
                "troop_queue",
                """
                SELECT player_id, planet_id, 0 AS account_scope
                FROM troop_queue
                WHERE player_id IS NOT NULL AND status = 'queued' AND finish_at <= ?
                """,
            ),
        )
        for table_name, sql in optional:
            if table_exists(conn, table_name):
                selects.append(sql)
                params.append(ts)

        cur = conn.cursor()
        cur.execute(" UNION ".join(selects), tuple(params))
        scopes: Dict[int, Dict[str, Any]] = {}
        for row in cur.fetchall():
            if row["player_id"] is None:
                continue
            uid = int(row["player_id"])
            scope = scopes.setdefault(
                uid,
                {"planet_ids": set(), "account_research": False},
            )
            if int(row["account_scope"] or 0):
                scope["account_research"] = True
            elif row["planet_id"] is not None:
                scope["planet_ids"].add(int(row["planet_id"]))
        return scopes
    finally:
        if own and conn is not None:
            conn.close()


def list_players_with_due_work(now: Optional[float] = None, conn=None) -> List[int]:
    """Backward-compatible distinct-player view of :func:`list_due_work_scopes`."""
    return sorted(list_due_work_scopes(now=now, conn=conn))


def _run_global_fleet_tail(result: Dict[str, Any], *, source: str) -> None:
    try:
        from .fleet_worker import run_fleet_worker

        fleet_result = run_fleet_worker(source=str(source or "cron"), force=True, persist=False)
        result["finished"]["fleet_arrivals"] = int(fleet_result.get("processed_arrivals") or 0)
        result["finished"]["fleet_returns"] = int(fleet_result.get("processed_returns") or 0)
        result["finished"]["fleet_holding"] = int(fleet_result.get("processed_holding") or 0)
        if fleet_result.get("errors"):
            result["errors"].extend(f"fleet: {err}" for err in fleet_result["errors"])
            result["ok"] = False
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(f"fleet tick: {exc}")
        logger.exception("queue tick fleet worker failed source=%s", source)


def _run_inbox_retention(result: Dict[str, Any], *, now: float, source: str) -> None:
    try:
        from .messages import purge_expired_inbox_messages

        purged = purge_expired_inbox_messages(now=now)
        result["finished"]["inbox_purged"] = int(purged)
    except Exception as exc:
        result["ok"] = False
        result["errors"].append(f"inbox retention: {exc}")
        logger.exception("queue tick inbox retention failed source=%s", source)


def run_tick(
    *,
    scope: str = "due",
    batch_size: int = 100,
    source: str = "cron",
    update_scores: bool = True,
    recalc_ranks: bool = False,
    persist: bool = True,
    include_fleet_tail: bool = True,
    include_inbox_retention: bool = True,
) -> Dict[str, Any]:
    """Process due queues globally in player batches (no request dedup).

    `include_fleet_tail=False` is the dedicated queue-sidecar mode. Fleet and
    World-Boss maintenance remain owned by `run_maintenance_worker.py`; otherwise
    a 5s queue cadence would accidentally execute the whole maintenance bag every
    5 seconds. Defaults preserve the historical cron/CLI behavior.
    """
    if scope != "due":
        raise ValueError(f"unsupported tick scope: {scope!r}")

    started = time.perf_counter()
    batch_size = max(1, int(batch_size))
    result = _empty_tick_result(source, scope)

    now = time.time()
    due_scopes = list_due_work_scopes(now=now)
    player_ids = sorted(due_scopes)
    result["players_processed"] = len(player_ids)
    result["planet_scopes_processed"] = sum(
        len(scope.get("planet_ids") or ()) for scope in due_scopes.values()
    )
    result["account_scopes_processed"] = sum(
        1 for scope in due_scopes.values() if bool(scope.get("account_research"))
    )

    logger.info(
        "queue tick start source=%s scope=%s players=%s planets=%s accounts=%s batch_size=%s queue_only=%s",
        source,
        scope,
        len(player_ids),
        result["planet_scopes_processed"],
        result["account_scopes_processed"],
        batch_size,
        not include_fleet_tail,
    )

    for offset in range(0, len(player_ids), batch_size):
        batch_players = player_ids[offset : offset + batch_size]
        result["batches"] += 1
        for pid in batch_players:
            scope = due_scopes[int(pid)]
            for due_planet_id in sorted(scope.get("planet_ids") or ()):
                batch_result = finish_due_work(
                    player_id=int(pid),
                    planet_id=int(due_planet_id),
                    now=now,
                    source=str(source or "cron"),
                    update_scores=update_scores,
                    recalc_ranks=recalc_ranks,
                    include_account_research=False,
                    include_fleet=False,
                    include_relocations=False,
                    skip_locked_planets=True,
                )
                _merge_tick_results(result, batch_result)

            if bool(scope.get("account_research")):
                batch_result = finish_due_work(
                    player_id=int(pid),
                    now=now,
                    source=str(source or "cron"),
                    update_scores=update_scores,
                    recalc_ranks=recalc_ranks,
                    include_planet_queues=False,
                    include_fleet=False,
                    include_relocations=False,
                )
                _merge_tick_results(result, batch_result)

    if include_fleet_tail:
        _run_global_fleet_tail(result, source=source)

    if include_inbox_retention:
        _run_inbox_retention(result, now=now, source=source)

    result["tick_elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    # Per-player finish duration is useful diagnostics, but wall clock is the
    # authoritative worker heartbeat duration (also meaningful on an idle tick).
    result["duration_ms"] = result["tick_elapsed_ms"]

    logger.info(
        "queue tick done source=%s finished=%s players=%s batches=%s duration_ms=%s errors=%s locked_skips=%s",
        source,
        result.get("finished"),
        len(result.get("affected_players") or []),
        result.get("batches"),
        result.get("duration_ms"),
        len(result.get("errors") or []),
        len(result.get("skipped_locked_planets") or []),
    )

    if persist:
        record_queue_tick_result(result)
    return result


def run_queue_tick(
    *,
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    source: str = "cron",
    update_scores: bool = True,
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
    update_scores: bool = True,
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
