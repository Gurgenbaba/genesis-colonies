"""Orbital Shipyard build queue — up to 3 jobs per planet, reorder, 60% cancel refund."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import begin_write_transaction, commit, db, rollback
from .fleet_defs import canonical_ship_key, get_ship, is_known_ship_key
from .models import lock_planet_for_update

MAX_SHIPYARD_QUEUE = 3
CANCEL_REFUND_RATIO = 0.6
QUEUE_STATUS_QUEUED = "queued"


def shipyard_queue_table_ready(conn) -> bool:
    from .fleet import table_exists

    if not table_exists(conn, "shipyard_queue"):
        return False
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(shipyard_queue);")
    cols = {str(r[1]) for r in cur.fetchall()}
    return "queue_position" in cols and "cost_metal" in cols


def _now() -> float:
    return time.time()


def _job_duration_seconds(ship_key: str, amount: int, shipyard_level: int) -> int:
    from .shipyard import _effective_build_seconds

    unit = max(1, _effective_build_seconds(ship_key, shipyard_level))
    return max(1, unit * max(1, int(amount)))


def list_shipyard_queue_rows(planet_id: int, *, conn) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM shipyard_queue
        WHERE planet_id = ? AND status = ?
        ORDER BY queue_position ASC, id ASC;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    return [dict(r) for r in cur.fetchall()]


def _renumber_positions(conn, planet_id: int) -> None:
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    cur = conn.cursor()
    for idx, row in enumerate(rows):
        cur.execute(
            "UPDATE shipyard_queue SET queue_position = ? WHERE id = ?;",
            (idx, int(row["id"])),
        )


def recalculate_queue_finish_times(
    planet_id: int,
    shipyard_level: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    ts = float(now if now is not None else _now())
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    cursor = conn.cursor()
    schedule_at = ts
    for row in rows:
        sk = canonical_ship_key(str(row["ship_key"]))
        amt = int(row["amount"] or 1)
        duration = _job_duration_seconds(sk, amt, shipyard_level)
        started = schedule_at
        finish = schedule_at + duration
        cursor.execute(
            """
            UPDATE shipyard_queue
            SET started_at = ?, finish_at = ?
            WHERE id = ?;
            """,
            (started, finish, int(row["id"])),
        )
        schedule_at = finish


def _refund_resources(
    conn,
    planet_id: int,
    *,
    metal: int,
    crystal: int,
    fuel_cells: float,
) -> None:
    if metal <= 0 and crystal <= 0 and fuel_cells <= 0:
        return
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal + ?,
            crystal = crystal + ?,
            fuel_cells = fuel_cells + ?
        WHERE id = ?;
        """,
        (int(metal), int(crystal), float(fuel_cells), int(planet_id)),
    )


def queue_count(planet_id: int, *, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM shipyard_queue
        WHERE planet_id = ? AND status = ?;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    row = cur.fetchone()
    return int(row["c"] if row else 0)


def enqueue_ship_build(
    *,
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    shipyard_level: int,
    cost: Mapping[str, int],
    conn,
) -> Tuple[bool, str, int | None]:
    if not shipyard_queue_table_ready(conn):
        return False, "fleet_unavailable", None
    if queue_count(planet_id, conn=conn) >= MAX_SHIPYARD_QUEUE:
        return False, "queue_full", None

    sk = canonical_ship_key(ship_key)
    qty = max(1, int(amount))
    now = _now()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(MAX(queue_position), -1) + 1 AS next_pos
        FROM shipyard_queue
        WHERE planet_id = ? AND status = ?;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    next_pos = int(cur.fetchone()["next_pos"] or 0)

    cur.execute(
        """
        INSERT INTO shipyard_queue (
            player_id, planet_id, ship_key, amount, status,
            started_at, finish_at, created_at,
            queue_position, cost_metal, cost_crystal, cost_fuel_cells
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            int(planet_id),
            sk,
            qty,
            QUEUE_STATUS_QUEUED,
            now,
            now,
            now,
            next_pos,
            int(cost.get("metal") or 0),
            int(cost.get("crystal") or 0),
            float(cost.get("fuel_cells") or 0),
        ),
    )
    job_id = int(cur.lastrowid)
    recalculate_queue_finish_times(planet_id, shipyard_level, conn=conn, now=now)
    return True, "", job_id


def cancel_queue_job(
    *,
    player_id: int,
    planet_id: int,
    job_id: int,
    shipyard_level: int,
    conn,
) -> Tuple[bool, str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM shipyard_queue
        WHERE id = ? AND planet_id = ? AND player_id = ? AND status = ?
        LIMIT 1;
        """,
        (int(job_id), int(planet_id), int(player_id), QUEUE_STATUS_QUEUED),
    )
    row = cur.fetchone()
    if not row:
        return False, "queue_job_not_found"

    job = dict(row)
    refund_m = int(int(job.get("cost_metal") or 0) * CANCEL_REFUND_RATIO)
    refund_c = int(int(job.get("cost_crystal") or 0) * CANCEL_REFUND_RATIO)
    refund_f = float(float(job.get("cost_fuel_cells") or 0) * CANCEL_REFUND_RATIO)

    cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(job_id),))
    _refund_resources(conn, planet_id, metal=refund_m, crystal=refund_c, fuel_cells=refund_f)
    _renumber_positions(conn, planet_id)
    recalculate_queue_finish_times(planet_id, shipyard_level, conn=conn)
    return True, ""


def move_queue_job(
    *,
    player_id: int,
    planet_id: int,
    job_id: int,
    direction: str,
    shipyard_level: int,
    conn,
) -> Tuple[bool, str]:
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    if len(rows) < 2:
        return False, "queue_move_invalid"

    idx = next((i for i, r in enumerate(rows) if int(r["id"]) == int(job_id)), None)
    if idx is None:
        return False, "queue_job_not_found"

    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(rows):
        return False, "queue_move_invalid"

    cur = conn.cursor()
    pos_a = int(rows[idx]["queue_position"])
    pos_b = int(rows[swap_idx]["queue_position"])
    id_a = int(rows[idx]["id"])
    id_b = int(rows[swap_idx]["id"])
    cur.execute("UPDATE shipyard_queue SET queue_position = ? WHERE id = ?;", (pos_b, id_a))
    cur.execute("UPDATE shipyard_queue SET queue_position = ? WHERE id = ?;", (pos_a, id_b))
    _renumber_positions(conn, planet_id)
    recalculate_queue_finish_times(planet_id, shipyard_level, conn=conn)
    return True, ""


def finish_due_shipyard_jobs_for_planet(
    conn,
    planet_id: int,
    player_id: int,
    *,
    now: Optional[float] = None,
) -> int:
    """Complete due shipyard jobs on a planet; credits ships to planet_ships."""
    if not shipyard_queue_table_ready(conn):
        return 0

    from .fleet import add_planet_ships, fleet_schema_ready
    from .shipyard import get_shipyard_level

    if not fleet_schema_ready(conn):
        return 0

    ts = float(now if now is not None else _now())
    from .queue_poll import DUE_TIME_EPSILON_SEC

    due_cutoff = ts + float(DUE_TIME_EPSILON_SEC)
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    if not rows:
        return 0

    sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
    completed = 0
    cur = conn.cursor()

    while rows:
        head = rows[0]
        if float(head["finish_at"]) > due_cutoff:
            break
        sk = canonical_ship_key(str(head["ship_key"]))
        qty = int(head["amount"] or 0)
        if is_known_ship_key(sk) and qty > 0:
            add_planet_ships(int(planet_id), int(player_id), {sk: qty}, conn=conn)
        cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(head["id"]),))
        completed += 1
        rows = list_shipyard_queue_rows(planet_id, conn=conn)

    if completed:
        _renumber_positions(conn, planet_id)
        recalculate_queue_finish_times(planet_id, sy_level, conn=conn, now=ts)

    return completed


def shipyard_queue_for_client(
    player_id: int,
    planet_id: int,
    shipyard_level: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Queue list + summary for API/UI."""
    ts = float(now if now is not None else _now())
    if shipyard_queue_table_ready(conn):
        finish_due_shipyard_jobs_for_planet(
            conn, int(planet_id), int(player_id), now=ts
        )

    rows = list_shipyard_queue_rows(planet_id, conn=conn) if shipyard_queue_table_ready(conn) else []
    jobs: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        sk = str(row["ship_key"])
        amt = int(row["amount"] or 0)
        finish_at = float(row["finish_at"] or 0)
        started_at = float(row["started_at"] or 0)
        total = _job_duration_seconds(sk, amt, shipyard_level)
        remaining = max(0, int(finish_at - ts))
        jobs.append(
            {
                "id": int(row["id"]),
                "ship_key": sk,
                "amount": amt,
                "queue_position": int(row.get("queue_position") or idx),
                "started_at": started_at,
                "finish_at": finish_at,
                "remaining": remaining,
                "total_seconds": total,
                "is_active": idx == 0,
                "cost_metal": int(row.get("cost_metal") or 0),
                "cost_crystal": int(row.get("cost_crystal") or 0),
                "cost_fuel_cells": int(float(row.get("cost_fuel_cells") or 0)),
            }
        )

    first_remaining = jobs[0]["remaining"] if jobs else 0
    return {
        "queue": jobs,
        "summary": {
            "count": len(jobs),
            "limit": MAX_SHIPYARD_QUEUE,
            "first_finish_in": first_remaining,
            "refund_percent": int(CANCEL_REFUND_RATIO * 100),
        },
    }
