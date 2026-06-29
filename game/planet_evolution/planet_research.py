"""Planet-scoped research queue and finish handling."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback
from ..models import (
    db,
    get_game_settings,
    get_planet_buildings,
    get_planet_owner_id,
    try_spend_resources_conn,
)
from ..ranking import invalidate_player_score_cache
from .definitions import get_research_def, get_research_defs
from .discoveries import try_roll_discovery
from .history import append_history
from .mechanics import compile_planet_mechanics, get_flag
from .planet_level import add_planet_xp
from .repository import get_locked_choices, get_planet_research_levels, get_planet_research_queue, get_planet_row
from .requirements import check_requirements


def _resolve_queue_limit(planet_id: int, conn: sqlite3.Connection) -> int:
    base = 2
    try:
        settings = get_game_settings(conn=conn)
        base = int(settings.get("planet_research_queue_limit", 2))
    except Exception:
        pass
    bonus = int(get_flag(planet_id, "planet_research_queue_bonus", 0, conn=conn) or 0)
    return max(1, base + bonus)


def _research_speed_mult(planet_id: int, conn: sqlite3.Connection) -> float:
    mult = 1.0
    try:
        settings = get_game_settings(conn=conn)
        mult = float(settings.get("planet_research_speed", 1.0))
    except Exception:
        pass
    bonus = float(get_flag(planet_id, "planet_research_speed_bonus", 0.0, conn=conn) or 0.0)
    return max(0.1, mult * (1.0 + bonus))


def compute_planet_research_cost(tech_key: str, target_level: int) -> Tuple[int, int]:
    cfg = get_research_def(tech_key) or {}
    factor = float(cfg.get("cost_factor") or 1.6)
    base_m = int(cfg.get("base_cost_m") or 0)
    base_c = int(cfg.get("base_cost_c") or 0)
    lvl = max(1, int(target_level))
    mult = factor ** (lvl - 1)
    return int(base_m * mult), int(base_c * mult)


def compute_planet_research_reward_xp(tech_key: str) -> Dict[str, Any]:
    """Canonical planet-XP grant for completing one level of planet research."""
    rdef = get_research_def(tech_key) or {}
    tier = int(rdef.get("tier") or 1)
    base = 25
    tier_bonus = tier * 15
    reward_xp = base + tier_bonus
    return {
        "reward_xp": int(reward_xp),
        "reward_xp_base": int(base),
        "reward_xp_tier_bonus": int(tier_bonus),
        "reward_tier": int(tier),
    }


def compute_planet_research_time(
    planet_id: int,
    tech_key: str,
    target_level: int,
    conn: sqlite3.Connection,
) -> float:
    cfg = get_research_def(tech_key) or {}
    base = float(cfg.get("base_time") or 600)
    tier = int(cfg.get("tier") or 1)
    tier_mult = 1.45 ** max(0, tier - 1)
    speed = _research_speed_mult(planet_id, conn)
    # Technical safety floor only (no balance cap). Keep >0 to avoid stuck/0-duration queues.
    return max(1.0, (base * tier_mult) / speed)


def finish_planet_research_jobs(conn: sqlite3.Connection, planet_id: int, now: float) -> int:
    from ..queue_poll import DUE_TIME_EPSILON_SEC

    due_cutoff = float(now) + float(DUE_TIME_EPSILON_SEC)
    cur = conn.cursor()
    finished = 0

    while True:
        cur.execute(
            """
            SELECT * FROM planet_research_queue
            WHERE planet_id = ?
            ORDER BY finish_at ASC, id ASC
            LIMIT 1;
            """,
            (int(planet_id),),
        )
        row = cur.fetchone()
        if not row or float(row["finish_at"]) > due_cutoff:
            break

        job = dict(row)
        tech_key = str(job["tech_key"])
        target = int(job["target_level"])
        levels = get_planet_research_levels(planet_id, conn=conn)
        levels[tech_key] = max(int(levels.get(tech_key, 0)), target)
        cur.execute("DELETE FROM planet_research_queue WHERE id = ?;", (int(job["id"]),))
        finished += 1

        cur.execute(
            """
            INSERT INTO planet_research_levels (planet_id, tech_key, level, unlocked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(planet_id, tech_key) DO UPDATE SET
                level = MAX(planet_research_levels.level, excluded.level),
                unlocked_at = COALESCE(planet_research_levels.unlocked_at, excluded.unlocked_at);
            """,
            (int(planet_id), tech_key, int(levels[tech_key]), float(now)),
        )

        rdef = get_research_def(tech_key) or {}
        append_history(
            planet_id,
            "planet_research_complete",
            str(rdef.get("label_key") or tech_key),
            body_key=str(rdef.get("description_key") or ""),
            payload={"tech_key": tech_key, "level": int(levels[tech_key])},
            conn=conn,
        )
        tier = int(rdef.get("tier") or 1)
        xp_grant = compute_planet_research_reward_xp(tech_key)
        add_planet_xp(planet_id, int(xp_grant["reward_xp"]), conn, reason=f"research:{tech_key}")

        compile_planet_mechanics(planet_id, conn)

        if tier >= 3:
            try_roll_discovery(planet_id, conn, source=f"research:{tech_key}")

    return finished


def queue_planet_research(
    planet_id: int,
    tech_key: str,
    *,
    player_id: Optional[int] = None,
    request_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))

        owner_id = get_planet_owner_id(int(planet_id))
        if owner_id is None:
            rollback(conn)
            return False, "planet_not_found", None

        if player_id is not None and int(owner_id) != int(player_id):
            rollback(conn)
            return False, "not_owner", None

        from ..queue_engine import finish_due_work

        finish_due_work(planet_id=int(planet_id), conn=conn, source="planet_research")

        planet = get_planet_row(planet_id, conn=conn)
        if not planet:
            rollback(conn)
            return False, "planet_not_found", None

        cfg = get_research_def(tech_key)
        if not cfg:
            rollback(conn)
            return False, "unknown_tech", None

        ok, missing = check_requirements(planet_id, cfg.get("requirements") or {}, conn)
        if not ok:
            rollback(conn)
            return False, "requirements", {"missing": missing}

        choice_group = cfg.get("choice_group")
        if choice_group:
            locked = get_locked_choices(planet_id, conn=conn)
            if str(choice_group) not in locked:
                mech = cfg.get("mechanics") or {}
                if mech.get("choice_required") or cfg.get("choice_options"):
                    rollback(conn)
                    return False, "choice_required", {"choice_group": choice_group}

        rows = get_planet_research_queue(planet_id, conn=conn)
        limit = _resolve_queue_limit(planet_id, conn)
        if len(rows) >= limit:
            rollback(conn)
            return False, "queue_full", {"queue_limit": limit}

        levels = get_planet_research_levels(planet_id, conn=conn)
        queued_same = sum(1 for r in rows if str(r["tech_key"]) == tech_key)
        current = int(levels.get(tech_key, 0) or 0)
        max_level = int(cfg.get("max_level") or 1)
        target = current + queued_same + 1
        if target > max_level:
            rollback(conn)
            return False, "max_level", {"max_level": max_level}

        cost_m, cost_c = compute_planet_research_cost(tech_key, target)
        if not try_spend_resources_conn(conn, int(planet_id), int(cost_m), int(cost_c)):
            rollback(conn)
            return False, "not_enough_resources", {"metal": cost_m, "crystal": cost_c}

        now = time.time()
        duration = compute_planet_research_time(planet_id, tech_key, target, conn)
        last_finish = max(float(r["finish_at"]) for r in rows) if rows else now
        start_at = max(now, last_finish)
        finish_at = start_at + duration

        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planet_research_queue (
                planet_id, tech_key, target_level, start_at, finish_at, request_id
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (int(planet_id), str(tech_key), int(target), float(start_at), float(finish_at), request_id),
        )
        job_id = int(cur.lastrowid)
        commit(conn)

        owner = get_planet_owner_id(int(planet_id))
        if owner:
            invalidate_player_score_cache(int(owner))

        return True, "ok", {
            "job_id": job_id,
            "tech_key": tech_key,
            "target_level": target,
            "seconds": int(duration),
            "finish_at": finish_at,
        }
    except Exception:
        if conn is not None:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def cancel_planet_research_job(
    planet_id: int,
    job_id: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        cur = conn.cursor()
        now = time.time()
        cur.execute(
            """
            SELECT id, tech_key, target_level, start_at, finish_at
            FROM planet_research_queue
            WHERE id = ? AND planet_id = ?
            LIMIT 1;
            """,
            (int(job_id), int(planet_id)),
        )
        row = cur.fetchone()
        if not row:
            rollback(conn)
            return False, "job_not_found"
        from ..queue_refund import refund_planet_evolution_research_job

        refund_planet_evolution_research_job(
            conn,
            int(planet_id),
            tech_key=str(row["tech_key"]),
            target_level=int(row["target_level"] or 0),
            start_time=float(row["start_at"] or row["finish_at"] or now),
            finish_time=float(row["finish_at"] or now),
            now=now,
        )
        cur.execute("DELETE FROM planet_research_queue WHERE id = ?;", (int(job_id),))
        commit(conn)
        return True, "ok"
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def get_planet_research_status(
    planet_id: int,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        now = time.time()
        finish_planet_research_jobs(conn, int(planet_id), now)

        levels = get_planet_research_levels(planet_id, conn=conn)
        queue = get_planet_research_queue(planet_id, conn=conn)
        locked = get_locked_choices(planet_id, conn=conn)
        buildings = get_planet_buildings(int(planet_id), conn=conn)

        techs: List[Dict[str, Any]] = []
        for tech_key, cfg in sorted(get_research_defs().items(), key=lambda x: (x[1].get("tier", 0), x[0])):
            req_ok, missing = check_requirements(planet_id, cfg.get("requirements") or {}, conn)
            current = int(levels.get(tech_key, 0) or 0)
            q_count = sum(1 for q in queue if str(q["tech_key"]) == tech_key)
            active = next((q for q in queue if str(q["tech_key"]) == tech_key), None)
            techs.append(
                {
                    "tech_key": tech_key,
                    "tier": int(cfg.get("tier") or 1),
                    "level": current,
                    "max_level": int(cfg.get("max_level") or 1),
                    "requirements_met": req_ok,
                    "missing_requirements": missing,
                    "queue_count": q_count,
                    "is_active": bool(active),
                    "active_job": dict(active) if active else None,
                    "choice_group": cfg.get("choice_group"),
                    "choice_options": cfg.get("choice_options"),
                    "choice_made": str(cfg.get("choice_group")) in locked if cfg.get("choice_group") else None,
                    "label_key": cfg.get("label_key"),
                    "description_key": cfg.get("description_key"),
                    "needs_research_lab": int(buildings.get("research_lab", 0) or 0) > 0,
                }
            )

        from ..queue_card import (
            card_queue_job_for_item,
            group_card_jobs_by_owner_key,
            map_planet_research_queue_to_card_jobs,
        )

        card_jobs = map_planet_research_queue_to_card_jobs(
            {
                "queue": queue,
            },
            now=now,
        )
        by_owner = group_card_jobs_by_owner_key(card_jobs)
        _attach_queue_jobs_to_planet_tech_rows(techs, by_owner)

        return {
            "planet_id": int(planet_id),
            "levels": levels,
            "queue": queue,
            "locked_choices": locked,
            "queue_limit": _resolve_queue_limit(planet_id, conn),
            "summary": {
                "count": len(queue),
                "limit": _resolve_queue_limit(planet_id, conn),
            },
            "card_jobs_by_owner": by_owner,
            "techs": techs,
        }
    finally:
        if own and conn is not None:
            conn.close()


def _attach_queue_jobs_to_planet_tech_rows(
    tech_rows: List[Dict[str, Any]],
    jobs_by_key: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """GC-536E: optional queue_job on each planet-tech row (presentation only)."""
    from ..queue_card import card_queue_job_for_item

    for row in tech_rows:
        owner_key = str(row.get("tech_key") or "")
        qj = card_queue_job_for_item(jobs_by_key, owner_key) if owner_key else None
        if qj:
            row["queue_job"] = dict(qj)
        elif "queue_job" in row:
            del row["queue_job"]
