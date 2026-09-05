"""Ascension quest queue and completion."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback
from ..exact_math import decimal_text, decimal_value
from ..models import db, try_spend_resources_conn
from ..ranking import invalidate_player_score_cache
from .definitions import get_ascension, get_ascensions
from .history import append_history
from .impact import impact_scopes, mechanics_impact_rows
from .mechanics import compile_planet_mechanics
from .planet_level import add_planet_xp
from .repository import get_planet_row
from .requirements import check_requirements


def check_ascension_requirements(
    planet_id: int,
    ascension_key: str,
    conn: sqlite3.Connection,
) -> Tuple[bool, list]:
    adef = get_ascension(ascension_key)
    if not adef:
        return False, ["unknown_ascension"]
    planet = get_planet_row(planet_id, conn=conn) or {}
    if planet.get("ascension_key"):
        return False, ["already_ascended"]
    if int(planet.get("planet_level") or 1) < 25:
        return False, ["planet_level>=25"]

    req = dict(adef.get("requirements") or {})
    cost = req.pop("cost", None)
    ok, missing = check_requirements(planet_id, req, conn)
    if not ok:
        return False, missing

    if isinstance(cost, dict):
        cur = conn.cursor()
        cur.execute("SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
        prow = cur.fetchone()
        if prow:
            if int(prow["metal"] or 0) < int(cost.get("metal") or 0):
                missing.append("cost:metal")
            if int(prow["crystal"] or 0) < int(cost.get("crystal") or 0):
                missing.append("cost:crystal")
        for res_key, amount in cost.items():
            if res_key in ("metal", "crystal"):
                continue
            cur.execute(
                """
                SELECT amount FROM planet_special_resources
                WHERE planet_id = ? AND resource_key = ? LIMIT 1;
                """,
                (int(planet_id), str(res_key)),
            )
            row = cur.fetchone()
            required = decimal_value(amount)
            available = decimal_value(row["amount"] if row else 0)
            if not row or available < required:
                missing.append(f"cost:{res_key}")

    return len(missing) == 0, missing


def ascension_cost_resources(ascension_key: str) -> Dict[str, int]:
    """Score-relevant resources spent to start an ascension (metal/crystal/fuel_cells only)."""
    adef = get_ascension(str(ascension_key)) or {}
    cost = dict((adef.get("requirements") or {}).get("cost") or {})
    return {
        "metal": int(cost.get("metal") or 0),
        "crystal": int(cost.get("crystal") or 0),
        "fuel_cells": int(cost.get("fuel_cells") or 0),
    }


def ascension_invested_resource_totals(
    planet_id: int,
    conn: sqlite3.Connection,
) -> Dict[str, int]:
    """GC-SCORE-E — ascension metal/crystal already spent (completed or active queue)."""
    keys: set[str] = set()
    planet = get_planet_row(int(planet_id), conn=conn)
    if planet and planet.get("ascension_key"):
        keys.add(str(planet["ascension_key"]))
    active = _get_planet_ascension_queue_row(int(planet_id), conn)
    if active and active.get("ascension_key"):
        keys.add(str(active["ascension_key"]))
    metal = 0
    crystal = 0
    fuel = 0
    for key in keys:
        cost = ascension_cost_resources(key)
        metal += int(cost["metal"])
        crystal += int(cost["crystal"])
        fuel += int(cost["fuel_cells"])
    return {"metal": metal, "crystal": crystal, "fuel_cells": fuel}


def _get_planet_ascension_queue_row(
    planet_id: int,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM planet_ascension_queue
        WHERE planet_id = ? AND state = 'active'
        ORDER BY start_at ASC
        LIMIT 1;
        """,
        (int(planet_id),),
    )
    row = cur.fetchone()
    return dict(row) if row else None


def _attach_queue_jobs_to_ascension_cards(
    cards: List[Dict[str, Any]],
    jobs_by_key: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    from ..queue_card import card_queue_job_for_item

    for card in cards:
        owner_key = str(card.get("ascension_key") or "")
        qj = card_queue_job_for_item(jobs_by_key, owner_key) if owner_key else None
        if qj:
            card["queue_job"] = dict(qj)
        elif "queue_job" in card:
            del card["queue_job"]


def get_ascension_status(
    planet_id: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Client payload for ascension cards + optional queue_job (GC-536E)."""
    own = conn is None
    if own:
        conn = db()
    try:
        now = time.time()
        planet = get_planet_row(planet_id, conn=conn) or {}
        active_row = _get_planet_ascension_queue_row(planet_id, conn)
        queue: List[Dict[str, Any]] = []
        if active_row:
            adef = get_ascension(str(active_row.get("ascension_key") or "")) or {}
            finish = float(active_row.get("finish_at") or 0)
            start = float(active_row.get("start_at") or 0)
            queue.append(
                {
                    **active_row,
                    "label_key": adef.get("label_key") or active_row.get("ascension_key"),
                    "remaining_seconds": max(0, int(finish - now)) if finish else 0,
                    "total_seconds": max(1, int(finish - start)) if finish > start else 1,
                }
            )

        ascensions: List[Dict[str, Any]] = []
        completed_key = planet.get("ascension_key")
        has_active = bool(active_row)
        for ascension_key, adef in sorted(get_ascensions().items()):
            ok, _missing = check_ascension_requirements(planet_id, ascension_key, conn)
            impact_rows = mechanics_impact_rows(adef.get("permanent_mechanics") or {})
            ascensions.append(
                {
                    "ascension_key": ascension_key,
                    "label_key": adef.get("label_key") or ascension_key,
                    "description_key": adef.get("description_key"),
                    "duration_days": float(adef.get("duration_days") or 7),
                    "impact": {
                        "current_label_key": f"ascension_{completed_key}" if completed_key else None,
                        "after_label_key": adef.get("label_key") or ascension_key,
                        "rows": impact_rows,
                        "scopes": impact_scopes(impact_rows),
                    },
                    "eligible": ok and not completed_key and not has_active,
                    "completed": str(completed_key) == str(ascension_key),
                    "is_active": bool(
                        active_row and str(active_row.get("ascension_key")) == str(ascension_key)
                    ),
                }
            )

        from ..queue_card import group_card_jobs_by_owner_key, map_ascension_queue_to_card_jobs

        status_payload = {
            "queue": queue,
            "summary": {"count": len(queue), "limit": 1},
        }
        card_jobs = map_ascension_queue_to_card_jobs(status_payload, now=now)
        by_owner = group_card_jobs_by_owner_key(card_jobs)
        status_payload["card_jobs_by_owner"] = by_owner
        _attach_queue_jobs_to_ascension_cards(ascensions, by_owner)

        return {
            **status_payload,
            "ascensions": ascensions,
            "completed_key": completed_key,
        }
    finally:
        if own and conn is not None:
            conn.close()


def start_ascension(
    planet_id: int,
    ascension_key: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    own = conn is None
    if own:
        conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))

        ok, missing = check_ascension_requirements(planet_id, ascension_key, conn)
        if not ok:
            rollback(conn)
            return False, "requirements", {"missing": missing}

        adef = get_ascension(ascension_key) or {}
        req = dict(adef.get("requirements") or {})
        cost = req.get("cost") or {}
        metal = int(cost.get("metal") or 0)
        crystal = int(cost.get("crystal") or 0)
        if metal or crystal:
            if not try_spend_resources_conn(conn, int(planet_id), metal, crystal):
                rollback(conn)
                return False, "not_enough_resources", None

        for res_key, amount in (cost or {}).items():
            if res_key in ("metal", "crystal"):
                continue
            cur = conn.cursor()
            amount_sql = decimal_text(amount)
            cur.execute(
                """
                UPDATE planet_special_resources
                SET amount = amount - CAST(? AS NUMERIC)
                WHERE planet_id = ? AND resource_key = ?
                  AND amount >= CAST(? AS NUMERIC);
                """,
                (amount_sql, int(planet_id), str(res_key), amount_sql),
            )
            if cur.rowcount <= 0:
                rollback(conn)
                return False, "not_enough_resources", {"resource": res_key}

        now = time.time()
        duration_days = float(adef.get("duration_days") or 7)
        finish_at = now + duration_days * 86400

        cur = conn.cursor()
        cur.execute("DELETE FROM planet_ascension_queue WHERE planet_id = ?;", (int(planet_id),))
        cur.execute(
            """
            INSERT INTO planet_ascension_queue (
                planet_id, ascension_key, start_at, finish_at, quest_stage, state
            ) VALUES (?, ?, ?, ?, 0, 'active');
            """,
            (int(planet_id), str(ascension_key), now, finish_at),
        )

        append_history(
            planet_id,
            "ascension_started",
            str(adef.get("label_key") or ascension_key),
            payload={"ascension_key": ascension_key, "finish_at": finish_at},
            conn=conn,
        )
        commit(conn)

        owner = (get_planet_row(planet_id, conn=conn) or {}).get("player_id")
        if owner:
            invalidate_player_score_cache(int(owner))

        return True, "ok", {"ascension_key": ascension_key, "finish_at": finish_at}
    except Exception:
        rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def finish_ascension_jobs(conn: sqlite3.Connection, planet_id: int, now: float) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM planet_ascension_queue
        WHERE planet_id = ? AND state = 'active' AND finish_at <= ?
        LIMIT 1;
        """,
        (int(planet_id), float(now)),
    )
    row = cur.fetchone()
    if not row:
        return 0

    job = dict(row)
    ascension_key = str(job["ascension_key"])
    adef = get_ascension(ascension_key) or {}

    cur.execute(
        """
        UPDATE planets SET ascension_key = ?, ascension_rank = MAX(ascension_rank, 1)
        WHERE id = ?;
        """,
        (ascension_key, int(planet_id)),
    )
    cur.execute(
        "UPDATE planet_ascension_queue SET state = 'completed' WHERE planet_id = ?;",
        (int(planet_id),),
    )

    append_history(
        planet_id,
        "ascension_complete",
        str(adef.get("label_key") or ascension_key),
        history_tag=f"ascended_{ascension_key}",
        payload={"ascension_key": ascension_key},
        visibility="global",
        conn=conn,
    )
    compile_planet_mechanics(planet_id, conn)
    add_planet_xp(planet_id, 500, conn, reason=f"ascension:{ascension_key}")
    return 1
