"""
Central queue finish engine for Genesis Colonies.

Single entry point for due build/research jobs, score updates, and rank snapshots.
"""

from __future__ import annotations

import copy
import logging
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from .db import begin_write_transaction, commit, db, in_transaction, rollback
from .models import (
    delete_build_job,
    get_build_queue_rows,
    get_planet_buildings,
    get_research_levels,
)

logger = logging.getLogger(__name__)

_ENGINE_LOCK = threading.RLock()

_MAX_FINISH_PASSES = 8

_BUILDING_KEYS = [
    "metal_mine", "crystal_mine", "solar_plant",
    "research_lab", "academy",
    "metal_storage", "crystal_storage", "fuel_storage",
    "command_center", "orbital_shipyard", "fuel_cell_plant", "defense_factory",
    "barracks", "radar_array", "shield_generator",
    "terraformer", "nanofactory", "geothermal_nexus",
    "planet_core_nexus",
]


def _empty_result(source: str) -> Dict[str, Any]:
    return {
        "ok": True,
        "source": source,
        "finished": {
            "buildings": 0,
            "research": 0,
            "planet_research": 0,
            "ascension": 0,
            "shipyard": 0,
            "defense": 0,
            "fleet_arrivals": 0,
            "fleet_returns": 0,
        },
        "affected_players": [],
        "affected_planets": [],
        "score_updates": 0,
        "rank_recalculated": False,
        "duration_ms": 0,
        "errors": [],
        "skipped_due_to_dedup": False,
        "dedup_scope_key": None,
        "derived_sync_count": 0,
    }


def _flask_request_active() -> bool:
    try:
        from flask import has_request_context

        return bool(has_request_context())
    except ImportError:
        return False


def clear_request_finish_dedup() -> None:
    """Reset request-level dedup (Flask teardown / tests)."""
    if not _flask_request_active():
        return
    from flask import g

    g.gc_finish_due_cache = None


def _get_dedup_state() -> Dict[str, Any]:
    from flask import g

    state = getattr(g, "gc_finish_due_cache", None)
    if state is None:
        state = {
            "completed_scopes": set(),
            "results_by_scope": {},
        }
        g.gc_finish_due_cache = state
    return state


def build_dedup_scope_key(
    player_id: Optional[int],
    planet_id: Optional[int],
) -> str:
    """
    Canonical scope for deduplication (source-independent).
    global | player:{id} | player:{id}:planet:{id}
    """
    if player_id is None and planet_id is None:
        return "global"
    if planet_id is not None:
        pid = int(player_id) if player_id is not None else 0
        return f"player:{pid}:planet:{int(planet_id)}"
    return f"player:{int(player_id)}"


def _scope_is_covered(scope_key: str, completed: Set[str]) -> bool:
    if scope_key in completed:
        return True
    # Planet scope covered when full player scope already ran this request.
    if ":planet:" in scope_key:
        player_prefix = scope_key.split(":planet:")[0]
        if player_prefix in completed:
            return True
    if scope_key == "global" and completed:
        return "global" in completed
    return False


def _register_scope_completed(scope_key: str, completed: Set[str]) -> None:
    completed.add(scope_key)


def _find_cached_result(
    scope_key: str,
    cache: Dict[str, Dict[str, Any]],
    completed: Set[str],
) -> Optional[Dict[str, Any]]:
    if not _scope_is_covered(scope_key, completed):
        return None
    if scope_key in cache:
        return cache[scope_key]
    if ":planet:" in scope_key:
        player_prefix = scope_key.split(":planet:")[0]
        if player_prefix in cache:
            return cache[player_prefix]
    return None


def _due_epsilon() -> float:
    from .queue_poll import DUE_TIME_EPSILON_SEC

    return float(DUE_TIME_EPSILON_SEC)


def finish_active_planet_due_work(
    player_id: int,
    planet_id: int,
    conn: sqlite3.Connection,
    *,
    source: str = "live_state",
    update_scores: bool = True,
    recalc_ranks: bool = True,
    manage_transaction: bool = True,
) -> Dict[str, Any]:
    """
    Finish due queue work on one planet, retrying while jobs remain due.

    Handles short build/research times and request-level dedup edge cases.
    """
    from .queue_poll import player_has_due_queue_work

    uid = int(player_id)
    pid = int(planet_id)
    src = str(source or "live_state")
    aggregate = _empty_result(src)
    last = aggregate

    for pass_idx in range(_MAX_FINISH_PASSES):
        last = finish_due_work_once(
            player_id=uid,
            planet_id=pid,
            conn=conn,
            source=src if pass_idx == 0 else f"{src}_retry",
            update_scores=update_scores,
            recalc_ranks=recalc_ranks if pass_idx == 0 else False,
            force=pass_idx > 0,
            manage_transaction=manage_transaction,
        )
        for key in aggregate["finished"]:
            aggregate["finished"][key] += int(last.get("finished", {}).get(key, 0) or 0)
        aggregate["score_updates"] += int(last.get("score_updates", 0) or 0)
        aggregate["derived_sync_count"] += int(last.get("derived_sync_count", 0) or 0)
        if last.get("errors"):
            aggregate["errors"].extend(last["errors"])
            aggregate["ok"] = False

        if not player_has_due_queue_work(uid, conn=conn, planet_id=pid):
            break
        finished_this_pass = sum(int(v or 0) for v in last.get("finished", {}).values())
        if finished_this_pass > 0:
            continue
        if last.get("skipped_due_to_dedup") and pass_idx + 1 < _MAX_FINISH_PASSES:
            continue
        break

    aggregate["dedup_scope_key"] = last.get("dedup_scope_key")
    return aggregate


def finish_player_due_work(
    player_id: int,
    conn: sqlite3.Connection,
    *,
    source: str = "live_state",
    update_scores: bool = True,
    recalc_ranks: bool = True,
    manage_transaction: bool = True,
) -> Dict[str, Any]:
    """
    Finish due queue work for one player (all colonies + account research).

    Prefer this over finish_active_planet_due_work for poll/page refresh so builds
    on inactive colonies still complete while the user is elsewhere.
    """
    from .queue_poll import player_has_due_queue_work

    uid = int(player_id)
    src = str(source or "live_state")
    aggregate = _empty_result(src)
    last = aggregate

    for pass_idx in range(_MAX_FINISH_PASSES):
        last = finish_due_work_once(
            player_id=uid,
            conn=conn,
            source=src if pass_idx == 0 else f"{src}_retry",
            update_scores=update_scores,
            recalc_ranks=recalc_ranks if pass_idx == 0 else False,
            force=pass_idx > 0,
            manage_transaction=manage_transaction,
        )
        for key in aggregate["finished"]:
            aggregate["finished"][key] += int(last.get("finished", {}).get(key, 0) or 0)
        aggregate["score_updates"] += int(last.get("score_updates", 0) or 0)
        aggregate["derived_sync_count"] += int(last.get("derived_sync_count", 0) or 0)
        if last.get("errors"):
            aggregate["errors"].extend(last["errors"])
            aggregate["ok"] = False

        if not player_has_due_queue_work(uid, conn=conn):
            break
        finished_this_pass = sum(int(v or 0) for v in last.get("finished", {}).values())
        if finished_this_pass > 0:
            continue
        if last.get("skipped_due_to_dedup") and pass_idx + 1 < _MAX_FINISH_PASSES:
            continue
        break

    aggregate["dedup_scope_key"] = last.get("dedup_scope_key")
    return aggregate


def finish_due_work_once(
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    now: Optional[float] = None,
    source: str = "system",
    conn: Optional[sqlite3.Connection] = None,
    *,
    update_scores: bool = True,
    recalc_ranks: bool = True,
    dedup: bool = True,
    force: bool = False,
    manage_transaction: bool = True,
) -> Dict[str, Any]:
    """
    Request-level deduplicated finish. Same canonical scope runs at most once per request.

    Uses Flask ``g.gc_finish_due_cache`` when a request context exists.
    Without Flask context: calls ``finish_due_work`` directly (no dedup).

    Skipped when dedup enabled and an equal or broader scope already finished.
    Bypass: force=True or dedup=False.
    """
    scope_key = build_dedup_scope_key(player_id, planet_id)

    if force or not dedup or not _flask_request_active():
        result = finish_due_work(
            player_id=player_id,
            planet_id=planet_id,
            now=now,
            source=source,
            conn=conn,
            update_scores=update_scores,
            recalc_ranks=recalc_ranks,
            manage_transaction=manage_transaction,
        )
        result["skipped_due_to_dedup"] = False
        result["dedup_scope_key"] = scope_key
        return result

    state = _get_dedup_state()
    completed: Set[str] = state["completed_scopes"]
    cache: Dict[str, Dict[str, Any]] = state["results_by_scope"]

    if _scope_is_covered(scope_key, completed):
        cached = _find_cached_result(scope_key, cache, completed)
        if cached is not None:
            out = copy.deepcopy(cached)
            out["skipped_due_to_dedup"] = True
            out["dedup_scope_key"] = scope_key
            out["source"] = str(source or out.get("source", "system"))
            out["duration_ms"] = 0
            logger.debug(
                "queue_engine dedup skip source=%s scope=%s",
                source,
                scope_key,
            )
            return out

    result = finish_due_work(
        player_id=player_id,
        planet_id=planet_id,
        now=now,
        source=source,
        conn=conn,
        update_scores=update_scores,
        recalc_ranks=recalc_ranks,
        manage_transaction=manage_transaction,
    )
    result["skipped_due_to_dedup"] = False
    result["dedup_scope_key"] = scope_key
    _register_scope_completed(scope_key, completed)
    cache[scope_key] = copy.deepcopy(result)
    return result


def finish_planet_build_jobs(
    conn: sqlite3.Connection,
    planet_id: int,
    player_id: int,
    now: float,
) -> int:
    """
    Finish due build jobs for one planet, one head job per loop iteration (sequential queue).
    Does not update scores (engine handles batch score/rank).
    """
    cur = conn.cursor()
    due_cutoff = float(now) + _due_epsilon()
    completed = 0
    build_completions: list[dict] = []

    while True:
        rows = get_build_queue_rows(int(planet_id), conn=conn)
        if not rows:
            break
        head = rows[0]
        if float(head["finish_time"]) > due_cutoff:
            break

        buildings = get_planet_buildings(int(planet_id), conn=conn)
        btype = str(head["building_type"])
        job_id = int(head["id"])
        if btype in buildings:
            buildings[btype] = int(buildings.get(btype, 0)) + 1
        delete_build_job(job_id, conn=conn)

        cur.execute(
            f"""
            UPDATE planet_buildings SET
            {", ".join(f"{k}=?" for k in _BUILDING_KEYS)}
            WHERE planet_id = ?;
            """,
            [int(buildings.get(k, 0)) for k in _BUILDING_KEYS] + [int(planet_id)],
        )
        completed += 1
        build_completions.append(
            {
                "building_type": btype,
                "source_event_id": f"build_finish:{job_id}",
            }
        )

    if build_completions:
        try:
            from .directives.progress import emit_build_complete_events

            emit_build_complete_events(
                int(player_id),
                build_completions,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception(
                "imperial_directives build progress failed player=%s planet=%s",
                player_id,
                planet_id,
            )
        try:
            from .planet_evolution.expansion_protocol import sync_establishment_state

            sync_establishment_state(int(planet_id), conn=conn)
        except Exception:
            logger.exception(
                "expansion establishment sync failed player=%s planet=%s",
                player_id,
                planet_id,
            )

    return completed


def finish_planet_shipyard_jobs(
    conn: sqlite3.Connection,
    planet_id: int,
    player_id: int,
    now: float,
) -> int:
    """
    Deliver due ships for one planet's shipyard queue (progressive per unit).
    Returns count of fully completed queue jobs.
    """
    from .shipyard_queue import _finish_due_shipyard_jobs_impl

    return _finish_due_shipyard_jobs_impl(
        conn, int(planet_id), int(player_id), now=float(now)
    )


def finish_planet_defense_jobs(
    conn: sqlite3.Connection,
    planet_id: int,
    player_id: int,
    now: float,
) -> int:
    """
    Deliver due defense units for one planet's defense queue (progressive per unit).
    Returns count of fully completed queue jobs.
    """
    from .defense import _finish_due_defense_jobs_impl

    return _finish_due_defense_jobs_impl(
        conn, int(planet_id), int(player_id), now=float(now)
    )


def finish_player_research_jobs(
    conn: sqlite3.Connection,
    user_id: int,
    now: float,
) -> int:
    """
    Finish due research jobs for one player, one head job per loop iteration (sequential queue).
    Does not update scores.
    """
    cur = conn.cursor()
    due_cutoff = float(now) + _due_epsilon()
    completed = 0
    research_completions: list[dict] = []

    while True:
        cur.execute(
            "SELECT * FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC, id ASC;",
            (int(user_id),),
        )
        rows = cur.fetchall()
        if not rows:
            break
        head = rows[0]
        if float(head["finish_at"]) > due_cutoff:
            break

        levels = get_research_levels(int(user_id), conn=conn)
        tech_key = str(head["tech_key"])
        job_id = int(head["id"])
        levels[tech_key] = int(levels.get(tech_key, 0)) + 1
        cur.execute("DELETE FROM research_queue WHERE id = ?;", (job_id,))

        for tkey, lvl in levels.items():
            cur.execute(
                """
                INSERT INTO research_levels (user_id, tech_key, level)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
                """,
                (int(user_id), str(tkey), int(lvl)),
            )
        completed += 1
        research_completions.append(
            {
                "tech_key": tech_key,
                "source_event_id": f"research_finish:{job_id}",
            }
        )

    if research_completions:
        try:
            from .directives.progress import emit_research_complete_events

            emit_research_complete_events(
                int(user_id),
                research_completions,
                conn=conn,
                now=float(now),
            )
        except Exception:
            logger.exception(
                "imperial_directives research progress failed player=%s",
                user_id,
            )

    return completed


def _resolve_planet_targets(
    conn: sqlite3.Connection,
    player_id: Optional[int],
    planet_id: Optional[int],
) -> List[Tuple[int, int]]:
    cur = conn.cursor()
    if planet_id is not None:
        cur.execute(
            "SELECT id, player_id FROM planets WHERE id = ? AND player_id IS NOT NULL LIMIT 1;",
            (int(planet_id),),
        )
        row = cur.fetchone()
        return [(int(row["id"]), int(row["player_id"]))] if row else []

    if player_id is not None:
        cur.execute(
            "SELECT id, player_id FROM planets WHERE player_id = ? ORDER BY id ASC;",
            (int(player_id),),
        )
        return [(int(r["id"]), int(r["player_id"])) for r in cur.fetchall()]

    cur.execute(
        """
        SELECT id AS planet_id, player_id
        FROM planets
        WHERE player_id IS NOT NULL
        ORDER BY id ASC;
        """
    )
    return [(int(r["planet_id"]), int(r["player_id"])) for r in cur.fetchall()]


def _resolve_research_targets(
    conn: sqlite3.Connection,
    player_id: Optional[int],
    planet_id: Optional[int],
) -> List[int]:
    if player_id is not None:
        return [int(player_id)]

    if planet_id is not None:
        cur = conn.cursor()
        cur.execute(
            "SELECT player_id FROM planets WHERE id = ? AND player_id IS NOT NULL LIMIT 1;",
            (int(planet_id),),
        )
        row = cur.fetchone()
        return [int(row["player_id"])] if row else []

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT user_id FROM research_queue ORDER BY user_id ASC;")
    return [int(r["user_id"]) for r in cur.fetchall()]


def finish_due_work(
    player_id: Optional[int] = None,
    planet_id: Optional[int] = None,
    now: Optional[float] = None,
    source: str = "system",
    conn: Optional[sqlite3.Connection] = None,
    *,
    update_scores: bool = True,
    recalc_ranks: bool = True,
    manage_transaction: bool = True,
) -> Dict[str, Any]:
    """
    Central finish pipeline: due build + research jobs, batch score, single rank pass.

    Scope:
      - planet_id set: that planet (+ owner research)
      - player_id set: all planets of player + their research
      - neither: global (all planets + users in research_queue) — admin/cron
    """
    started = time.perf_counter()
    result = _empty_result(str(source or "system"))
    owns_conn = conn is None
    if owns_conn:
        conn = db()

    if now is None:
        now = time.time()

    affected_players: Set[int] = set()
    affected_planets: Set[int] = set()

    def _execute_finish() -> None:
        nonlocal result, affected_players, affected_planets

        planet_targets = _resolve_planet_targets(conn, player_id, planet_id)
        research_targets = _resolve_research_targets(conn, player_id, planet_id)

        for pid_planet, pid_player in planet_targets:
            try:
                n = finish_planet_build_jobs(conn, pid_planet, pid_player, float(now))
                if n > 0:
                    result["finished"]["buildings"] += n
                    affected_players.add(pid_player)
                    affected_planets.add(pid_planet)
            except Exception as exc:
                result["ok"] = False
                msg = f"build planet={pid_planet} player={pid_player}: {exc}"
                result["errors"].append(msg)
                logger.exception("queue_engine build finish failed: %s", msg)

            try:
                from .planet_evolution.repository import evolution_schema_ready

                if evolution_schema_ready(conn):
                    from .planet_evolution.planet_research import finish_planet_research_jobs
                    from .planet_evolution.ascension import finish_ascension_jobs

                    n_pr = finish_planet_research_jobs(conn, pid_planet, float(now))
                    if n_pr > 0:
                        result["finished"]["planet_research"] += n_pr
                        affected_players.add(pid_player)
                        affected_planets.add(pid_planet)
                    n_as = finish_ascension_jobs(conn, pid_planet, float(now))
                    if n_as > 0:
                        result["finished"]["ascension"] += n_as
                        affected_players.add(pid_player)
                        affected_planets.add(pid_planet)
            except Exception as exc:
                result["ok"] = False
                msg = f"planet_evolution planet={pid_planet}: {exc}"
                result["errors"].append(msg)
                logger.exception("queue_engine planet evolution finish failed: %s", msg)

            try:
                n_sy = finish_planet_shipyard_jobs(
                    conn, pid_planet, pid_player, float(now)
                )
                if n_sy > 0:
                    result["finished"]["shipyard"] += n_sy
                    affected_players.add(pid_player)
                    affected_planets.add(pid_planet)
            except Exception as exc:
                result["ok"] = False
                msg = f"shipyard planet={pid_planet}: {exc}"
                result["errors"].append(msg)
                logger.exception("queue_engine shipyard finish failed: %s", msg)

            try:
                n_def = finish_planet_defense_jobs(
                    conn, pid_planet, pid_player, float(now)
                )
                if n_def > 0:
                    result["finished"]["defense"] += n_def
                    affected_players.add(pid_player)
                    affected_planets.add(pid_planet)
            except Exception as exc:
                result["ok"] = False
                msg = f"defense planet={pid_planet}: {exc}"
                result["errors"].append(msg)
                logger.exception("queue_engine defense finish failed: %s", msg)

        for uid in research_targets:
            try:
                n = finish_player_research_jobs(conn, uid, float(now))
                if n > 0:
                    result["finished"]["research"] += n
                    affected_players.add(uid)
            except Exception as exc:
                result["ok"] = False
                msg = f"research user={uid}: {exc}"
                result["errors"].append(msg)
                logger.exception("queue_engine research finish failed: %s", msg)

        try:
            from .fleet import fleet_schema_ready, process_fleet_tick

            if fleet_schema_ready(conn):
                fleet_player = int(player_id) if player_id is not None else None
                fleet_result = process_fleet_tick(player_id=fleet_player, now=float(now), conn=conn)
                result["finished"]["fleet_arrivals"] += int(fleet_result.get("processed_arrivals") or 0)
                result["finished"]["fleet_returns"] += int(fleet_result.get("processed_returns") or 0)
                if fleet_result.get("errors"):
                    for err in fleet_result["errors"]:
                        result["errors"].append(f"fleet: {err}")
        except Exception as exc:
            result["ok"] = False
            msg = f"fleet tick: {exc}"
            result["errors"].append(msg)
            logger.exception("queue_engine fleet tick failed: %s", msg)

        if update_scores and affected_players:
            from .score_events import apply_score_updates_for_players

            result["score_updates"] = apply_score_updates_for_players(
                affected_players,
                conn=conn,
                recalc_ranks=recalc_ranks,
                reason=str(source or "queue_finish"),
            )
            result["rank_recalculated"] = bool(recalc_ranks and result["score_updates"] > 0)

        derived_synced = 0
        account_wide_sync = (
            int(result["finished"]["research"]) > 0
            or int(result["finished"]["planet_research"]) > 0
            or int(result["finished"]["ascension"]) > 0
        )
        if affected_planets or (affected_players and account_wide_sync):
            from .resources import sync_derived_state_after_queue_finish

            if account_wide_sync:
                derived_synced = sync_derived_state_after_queue_finish(
                    player_ids=affected_players,
                    conn=conn,
                )
            else:
                derived_synced = sync_derived_state_after_queue_finish(
                    planet_ids=affected_planets,
                    conn=conn,
                )
        result["derived_sync_count"] = int(derived_synced)

    try:
        if manage_transaction:
            if in_transaction(conn):
                _execute_finish()
            else:
                with _ENGINE_LOCK:
                    begin_write_transaction(conn)
                    _execute_finish()
                    if owns_conn:
                        commit(conn)
        else:
            _execute_finish()

    except Exception as exc:
        if manage_transaction and owns_conn:
            rollback(conn)
        result["ok"] = False
        result["errors"].append(str(exc))
        logger.exception("queue_engine.finish_due_work failed source=%s", source)
        raise
    finally:
        if owns_conn and conn is not None:
            conn.close()

    result["affected_players"] = sorted(affected_players)
    result["affected_planets"] = sorted(affected_planets)
    result["duration_ms"] = int((time.perf_counter() - started) * 1000)
    result.setdefault("skipped_due_to_dedup", False)
    result.setdefault("dedup_scope_key", build_dedup_scope_key(player_id, planet_id))
    return result
