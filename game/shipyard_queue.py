"""Orbital Shipyard build queue — up to 3 jobs per planet, reorder, cancel refund via queue_refund."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import begin_write_transaction, commit, db, rollback, table_columns
from .fleet_defs import canonical_ship_key, get_ship, is_known_ship_key
from .models import lock_planet_for_update
from .queue_refund import refund_from_stored_costs, refund_summary_percents

MAX_SHIPYARD_QUEUE = 3  # fallback default; prefer get_shipyard_queue_limit()
QUEUE_STATUS_QUEUED = "queued"


def get_shipyard_queue_limit(*, conn=None, planet_id: int | None = None) -> int:
    """Max concurrent shipyard jobs per planet (Admin → Balance + Stellar Forge rank bonus)."""
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = (settings or {}).get("shipyard_queue_limit", MAX_SHIPYARD_QUEUE)
        limit = int(float(raw))
        limit = max(1, min(20, limit))
    except (TypeError, ValueError):
        limit = MAX_SHIPYARD_QUEUE
    if planet_id is not None:
        from .shipyard import forge_rank_for_planet
        from .stellar_forge.formulas import queue_slot_bonus

        forge_rank = forge_rank_for_planet(planet_id, conn=conn)
        limit += queue_slot_bonus(forge_rank)
    return limit


def shipyard_queue_table_ready(conn) -> bool:
    from .fleet import table_exists

    if not table_exists(conn, "shipyard_queue"):
        return False
    cols = table_columns(conn, "shipyard_queue")
    return "queue_position" in cols and "cost_metal" in cols


def _now() -> float:
    return time.time()


def _unit_build_seconds(
    ship_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
) -> int:
    from .shipyard import unit_build_seconds

    return max(
        1,
        unit_build_seconds(ship_key, shipyard_level, conn=conn, planet_id=planet_id),
    )


def _batch_capacity_for_ship(
    ship_key: str,
    shipyard_level: int,
    *,
    planet_id: int | None = None,
    conn=None,
) -> int:
    from .shipyard import forge_rank_for_planet, orbital_production_batch_capacity

    _ = ship_key
    forge_rank = forge_rank_for_planet(planet_id, conn=conn)
    return orbital_production_batch_capacity(shipyard_level, forge_rank)


def _job_duration_seconds(
    ship_key: str,
    amount: int,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
) -> int:
    from .shipyard import production_job_duration_seconds

    unit = _unit_build_seconds(ship_key, shipyard_level, conn=conn, planet_id=planet_id)
    cap = _batch_capacity_for_ship(ship_key, shipyard_level, planet_id=planet_id, conn=conn)
    return production_job_duration_seconds(
        unit_seconds=unit, amount=int(amount), batch_capacity=cap
    )


def _job_scheduled_duration_seconds(row: Mapping[str, Any]) -> int:
    started = float(row.get("started_at") or 0)
    finish = float(row.get("finish_at") or 0)
    return max(1, int(finish - started))


def _planet_id_from_row(row: Mapping[str, Any]) -> int | None:
    try:
        pid = int(row.get("planet_id") or 0)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def _job_total_units(
    row: Mapping[str, Any], shipyard_level: int, *, conn
) -> int:
    """Original order size (stable while amount tracks remaining units)."""
    from .shipyard import production_infer_total_units

    sk = canonical_ship_key(str(row["ship_key"]))
    remaining = max(0, int(row.get("amount") or 0))
    pid = _planet_id_from_row(row)
    unit_sec = _unit_build_seconds(
        sk, shipyard_level, conn=conn, planet_id=pid
    )
    cap = _batch_capacity_for_ship(sk, shipyard_level, planet_id=pid, conn=conn)
    return production_infer_total_units(
        remaining=remaining,
        scheduled_duration=_job_scheduled_duration_seconds(row),
        unit_seconds=unit_sec,
        batch_capacity=cap,
    )


def progressive_units_to_deliver(
    row: Mapping[str, Any],
    shipyard_level: int,
    *,
    now: float,
    conn,
) -> int:
    """How many ships from this job are due for delivery at ``now``."""
    from .queue_poll import DUE_TIME_EPSILON_SEC
    from .shipyard import production_progressive_units_to_deliver

    remaining = max(0, int(row.get("amount") or 0))
    if remaining <= 0:
        return 0

    sk = canonical_ship_key(str(row["ship_key"]))
    pid = _planet_id_from_row(row)
    unit_sec = _unit_build_seconds(
        sk, shipyard_level, conn=conn, planet_id=pid
    )
    cap = _batch_capacity_for_ship(sk, shipyard_level, planet_id=pid, conn=conn)
    total = _job_total_units(row, shipyard_level, conn=conn)
    return production_progressive_units_to_deliver(
        remaining=remaining,
        total_units=total,
        started_at=float(row.get("started_at") or 0),
        finish_at=float(row.get("finish_at") or 0),
        unit_seconds=unit_sec,
        batch_capacity=cap,
        now=float(now),
        epsilon=float(DUE_TIME_EPSILON_SEC),
    )


def _next_unit_finish_at(
    row: Mapping[str, Any], shipyard_level: int, *, conn
) -> float:
    """Unix time when the next production batch in this job completes."""
    from .shipyard import production_next_batch_finish_at

    sk = canonical_ship_key(str(row["ship_key"]))
    pid = _planet_id_from_row(row)
    started = float(row.get("started_at") or 0)
    unit_sec = _unit_build_seconds(
        sk, shipyard_level, conn=conn, planet_id=pid
    )
    cap = _batch_capacity_for_ship(sk, shipyard_level, planet_id=pid, conn=conn)
    total = _job_total_units(row, shipyard_level, conn=conn)
    remaining = max(0, int(row.get("amount") or 0))
    delivered = max(0, total - remaining)
    return production_next_batch_finish_at(
        started_at=started,
        delivered=delivered,
        unit_seconds=unit_sec,
        batch_capacity=cap,
    )


def _job_row_for_client(
    row: Mapping[str, Any],
    *,
    idx: int,
    shipyard_level: int,
    now: float,
    conn,
) -> Dict[str, Any]:
    from .fleet_defs import ship_icon_static_path
    from .shipyard import production_live_order_remaining_seconds

    sk = canonical_ship_key(str(row["ship_key"]))
    pid = _planet_id_from_row(row)
    amount_remaining = max(0, int(row.get("amount") or 0))
    total_units = _job_total_units(row, shipyard_level, conn=conn)
    units_delivered = max(0, total_units - amount_remaining)
    unit_sec = _unit_build_seconds(
        sk, shipyard_level, conn=conn, planet_id=pid
    )
    started_at = float(row.get("started_at") or 0)
    finish_at = float(row.get("finish_at") or 0)
    is_active = idx == 0
    cap = _batch_capacity_for_ship(sk, shipyard_level, planet_id=pid, conn=conn)

    if is_active and amount_remaining > 0:
        order_remaining = production_live_order_remaining_seconds(
            remaining_amount=amount_remaining,
            unit_seconds=unit_sec,
            batch_capacity=cap,
            started_at=started_at,
            delivered=units_delivered,
            now=float(now),
            scheduled_duration=_job_scheduled_duration_seconds(row),
            total_units=total_units,
        )
        finish_at = float(now) + order_remaining
        next_finish_at = _next_unit_finish_at(row, shipyard_level, conn=conn)
        unit_remaining = max(0, int(next_finish_at - now))
        order_total_seconds = max(
            1,
            int(finish_at - started_at) if started_at > 0 else order_remaining,
        )
        remaining = order_remaining
        progress_total = order_total_seconds
    else:
        order_remaining = max(0, int(finish_at - now))
        order_total_seconds = _job_scheduled_duration_seconds(row)
        next_finish_at = finish_at
        unit_remaining = 0
        remaining = order_remaining
        progress_total = order_total_seconds

    from .logic import normalize_queue_job_timer_fields

    timer_fields = normalize_queue_job_timer_fields(
        finish_at=finish_at,
        remaining=order_remaining,
        is_active=is_active,
        next_finish_at=next_finish_at,
    )

    return {
        "id": int(row["id"]),
        "ship_key": sk,
        "icon": ship_icon_static_path(sk),
        # Display / mini-queue use remaining units still in this job (not original total).
        "amount": amount_remaining,
        "amount_total": total_units,
        "amount_remaining": amount_remaining,
        "units_delivered": units_delivered,
        "unit_seconds": unit_sec,
        "unit_remaining": unit_remaining,
        "order_remaining": order_remaining,
        "queue_position": int(row.get("queue_position") or idx),
        "started_at": started_at,
        "total_seconds": max(1, progress_total),
        "order_total_seconds": order_total_seconds,
        "is_active": is_active,
        "cost_metal": int(row.get("cost_metal") or 0),
        "cost_crystal": int(row.get("cost_crystal") or 0),
        "cost_fuel_cells": int(float(row.get("cost_fuel_cells") or 0)),
        **timer_fields,
    }


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
        duration = _job_duration_seconds(
            sk, amt, shipyard_level, conn=conn, planet_id=int(planet_id)
        )
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


def sync_shipyard_queue_finish_times(
    planet_id: int,
    shipyard_level: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """Align finish_at with live batch remaining; preserve head started_at when params match."""
    from .shipyard import (
        production_live_order_remaining_seconds,
        production_schedule_matches_live_params,
    )

    if not shipyard_queue_table_ready(conn):
        return
    ts = float(now if now is not None else _now())
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    if not rows:
        return

    cur = conn.cursor()
    head = rows[0]
    rem = max(0, int(head.get("amount") or 0))
    if rem > 0:
        sk = canonical_ship_key(str(head["ship_key"]))
        unit = _unit_build_seconds(
            sk, shipyard_level, conn=conn, planet_id=int(planet_id)
        )
        cap = _batch_capacity_for_ship(sk, shipyard_level, planet_id=int(planet_id), conn=conn)
        scheduled = _job_scheduled_duration_seconds(head)
        # Prefer remaining as total when schedule no longer matches live yard params.
        total_guess = _job_total_units(head, shipyard_level, conn=conn)
        params_ok = production_schedule_matches_live_params(
            scheduled_duration=scheduled,
            total_units=max(rem, total_guess),
            unit_seconds=unit,
            batch_capacity=cap,
        )
        if params_ok:
            total = max(rem, total_guess)
            delivered = max(0, total - rem)
            started_at = float(head.get("started_at") or ts)
        else:
            total = rem
            delivered = 0
            started_at = ts
        live_rem = production_live_order_remaining_seconds(
            remaining_amount=rem,
            unit_seconds=unit,
            batch_capacity=cap,
            started_at=started_at,
            delivered=delivered,
            now=ts,
            scheduled_duration=scheduled,
            total_units=max(rem, total_guess),
        )
        new_finish = ts + live_rem
        old_finish = float(head.get("finish_at") or 0)
        old_started = float(head.get("started_at") or 0)
        if (not params_ok and abs(started_at - old_started) >= 0.5) or abs(
            new_finish - old_finish
        ) >= 0.5:
            if params_ok:
                cur.execute(
                    "UPDATE shipyard_queue SET finish_at = ? WHERE id = ?;",
                    (new_finish, int(head["id"])),
                )
            else:
                cur.execute(
                    """
                    UPDATE shipyard_queue
                    SET started_at = ?, finish_at = ?
                    WHERE id = ?;
                    """,
                    (started_at, new_finish, int(head["id"])),
                )
            head = {**head, "finish_at": new_finish, "started_at": started_at}
        schedule_at = float(head.get("finish_at") or (ts + live_rem))
    else:
        schedule_at = ts

    for row in rows[1:]:
        sk = canonical_ship_key(str(row["ship_key"]))
        amt = max(1, int(row.get("amount") or 1))
        duration = _job_duration_seconds(
            sk, amt, shipyard_level, conn=conn, planet_id=int(planet_id)
        )
        started = schedule_at
        finish = schedule_at + duration
        cur.execute(
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


def planet_ids_with_shipyard_queue(
    planet_ids: Sequence[int],
    conn=None,
    *,
    now: Optional[float] = None,
) -> set[int]:
    """
    GC-PLANET-UI-001: DISTINCT planet_ids with at least one queued shipyard job
    that is not yet due (finish_at > now). Read-only — no finish/side effects.
    """
    ids = [int(pid) for pid in planet_ids if pid is not None]
    if not ids:
        return set()

    own = False
    if conn is None:
        conn = db()
        own = True

    try:
        if not shipyard_queue_table_ready(conn):
            return set()
        ts = float(time.time() if now is None else now)
        placeholders = ",".join("?" for _ in ids)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT DISTINCT planet_id
            FROM shipyard_queue
            WHERE planet_id IN ({placeholders})
              AND status = ?
              AND finish_at > ?;
            """,
            (*ids, QUEUE_STATUS_QUEUED, ts),
        )
        return {int(r["planet_id"]) for r in cur.fetchall()}
    finally:
        if own and conn is not None:
            conn.close()


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
    from .options import vacation_blocks_outbound

    ok_vacation, vac_reason = vacation_blocks_outbound(int(player_id), conn=conn)
    if not ok_vacation:
        return False, vac_reason, None
    if not shipyard_queue_table_ready(conn):
        return False, "fleet_unavailable", None
    if queue_count(planet_id, conn=conn) >= get_shipyard_queue_limit(conn=conn, planet_id=planet_id):
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
    now = _now()
    refund = refund_from_stored_costs(
        conn,
        int(planet_id),
        job,
        start_time=float(job.get("started_at") or job.get("created_at") or now),
        finish_time=float(job.get("finish_at") or now),
        now=now,
    )

    cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(job_id),))
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
    """Deliver due ships on a planet; returns count of fully completed queue jobs."""
    return _finish_due_shipyard_jobs_impl(
        conn,
        int(planet_id),
        int(player_id),
        now=float(now if now is not None else _now()),
    )


def _finish_due_shipyard_jobs_impl(
    conn,
    planet_id: int,
    player_id: int,
    *,
    now: float,
) -> int:
    """Progressive per-ship delivery for the active shipyard job(s)."""
    if not shipyard_queue_table_ready(conn):
        return 0

    from .fleet import add_planet_ships, fleet_schema_ready
    from .shipyard import get_shipyard_level

    if not fleet_schema_ready(conn):
        return 0

    ts = float(now)
    rows = list_shipyard_queue_rows(planet_id, conn=conn)
    if not rows:
        return 0

    sy_level = get_shipyard_level(player_id, planet_id, conn=conn)
    completed_jobs = 0
    cur = conn.cursor()

    while rows:
        head = rows[0]
        remaining_amt = max(0, int(head.get("amount") or 0))
        if remaining_amt <= 0:
            cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(head["id"]),))
            try:
                from .activity_xp import SOURCE_SHIPYARD_FINISH, grant_queue_job_activity_xp

                grant_queue_job_activity_xp(
                    int(player_id),
                    int(planet_id),
                    SOURCE_SHIPYARD_FINISH,
                    int(head["id"]),
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "activity_xp shipyard grant failed player=%s job=%s",
                    player_id,
                    head["id"],
                )
            completed_jobs += 1
            rows = list_shipyard_queue_rows(planet_id, conn=conn)
            continue

        to_deliver = progressive_units_to_deliver(head, sy_level, now=ts, conn=conn)
        finish_at = float(head.get("finish_at") or 0)
        if to_deliver <= 0 and remaining_amt > 0 and finish_at > 0 and ts + 0.001 >= finish_at:
            to_deliver = remaining_amt
        if to_deliver <= 0:
            break

        sk = canonical_ship_key(str(head["ship_key"]))
        if is_known_ship_key(sk):
            add_planet_ships(int(planet_id), int(player_id), {sk: to_deliver}, conn=conn)
            try:
                from .stellar_forge import record_hull_mass_delivery

                record_hull_mass_delivery(int(planet_id), sk, to_deliver, conn=conn, now=ts)
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "stellar_forge hull mass record failed player=%s planet=%s",
                    player_id,
                    planet_id,
                )
            try:
                from .directives.progress import emit_ship_built_events

                delivered_before = remaining_amt
                emit_ship_built_events(
                    int(player_id),
                    ship_key=sk,
                    amount=to_deliver,
                    job_id=int(head["id"]),
                    delivered_before=delivered_before,
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "imperial_directives shipyard progress failed player=%s",
                    player_id,
                )

        remaining = max(0, int(head["amount"] or 0) - to_deliver)
        if remaining <= 0:
            cur.execute("DELETE FROM shipyard_queue WHERE id = ?;", (int(head["id"]),))
            try:
                from .activity_xp import SOURCE_SHIPYARD_FINISH, grant_queue_job_activity_xp

                grant_queue_job_activity_xp(
                    int(player_id),
                    int(planet_id),
                    SOURCE_SHIPYARD_FINISH,
                    int(head["id"]),
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "activity_xp shipyard grant failed player=%s job=%s",
                    player_id,
                    head["id"],
                )
            completed_jobs += 1
            rows = list_shipyard_queue_rows(planet_id, conn=conn)
            continue

        cur.execute(
            "UPDATE shipyard_queue SET amount = ? WHERE id = ?;",
            (remaining, int(head["id"])),
        )
        sync_shipyard_queue_finish_times(planet_id, sy_level, conn=conn, now=ts)
        break

    if completed_jobs:
        _renumber_positions(conn, planet_id)
        recalculate_queue_finish_times(planet_id, sy_level, conn=conn, now=ts)

    return completed_jobs


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
        sync_shipyard_queue_finish_times(
            int(planet_id), int(shipyard_level), conn=conn, now=ts
        )

    rows = list_shipyard_queue_rows(planet_id, conn=conn) if shipyard_queue_table_ready(conn) else []
    jobs: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        jobs.append(
            _job_row_for_client(
                row,
                idx=idx,
                shipyard_level=shipyard_level,
                now=ts,
                conn=conn,
            )
        )

    first_remaining = jobs[0]["remaining"] if jobs else 0
    summary = {
        "count": len(jobs),
        "limit": get_shipyard_queue_limit(conn=conn, planet_id=planet_id),
        "first_finish_in": first_remaining,
    }
    summary.update(refund_summary_percents())
    return {
        "queue": jobs,
        "summary": summary,
    }
