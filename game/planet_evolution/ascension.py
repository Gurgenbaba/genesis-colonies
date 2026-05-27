"""Ascension quest queue and completion."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import begin_write_transaction, commit, lock_planet_for_update, rollback
from ..models import db, try_spend_resources_conn
from ..ranking import invalidate_player_score_cache
from .definitions import get_ascension
from .history import append_history
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
            if float(prow["metal"] or 0) < float(cost.get("metal") or 0):
                missing.append("cost:metal")
            if float(prow["crystal"] or 0) < float(cost.get("crystal") or 0):
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
            if not row or float(row["amount"] or 0) < float(amount):
                missing.append(f"cost:{res_key}")

    return len(missing) == 0, missing


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
            cur.execute(
                """
                UPDATE planet_special_resources SET amount = amount - ?
                WHERE planet_id = ? AND resource_key = ? AND amount >= ?;
                """,
                (float(amount), int(planet_id), str(res_key), float(amount)),
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
