"""Planet-scoped defense build queue — costs upfront, delivery via queue_engine."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .db import begin_write_transaction, commit, db, in_transaction, rollback, table_columns, table_exists
from .defense_defs import (
    ACTIVE_DEFENSE_KEYS,
    DEFENSES,
    get_defense,
    is_known_defense_key,
    unit_build_cost,
)
from .models import (
    add_planet_defense,
    defense_schema_ready,
    get_planet_buildings,
    get_planet_defense,
    get_research_levels,
    _legacy_i64_cost_snapshot,
    lock_planet_for_update,
    resource_db_param,
)
from .queue_refund import refund_summary_percents, stored_cost_int

MAX_DEFENSE_QUEUE = 3
QUEUE_STATUS_QUEUED = "queued"
BUILD_TIME_LEVEL_FACTOR = 0.90


def _now() -> float:
    return time.time()


def defense_queue_table_ready(conn) -> bool:
    if not table_exists(conn, "defense_queue"):
        return False
    cols = table_columns(conn, "defense_queue")
    return "queue_position" in cols and "cost_metal" in cols


def get_defense_queue_limit(*, conn=None) -> int:
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = (settings or {}).get("defense_queue_limit")
        if raw is None:
            raw = (settings or {}).get("shipyard_queue_limit", MAX_DEFENSE_QUEUE)
        limit = int(float(raw))
        return max(1, min(20, limit))
    except (TypeError, ValueError):
        return MAX_DEFENSE_QUEUE


def _defense_speed_multiplier(*, conn=None) -> float:
    try:
        from .models import get_game_settings

        settings = get_game_settings(conn=conn) if conn is not None else get_game_settings()
        raw = float((settings or {}).get("shipyard_speed", 1.0) or 1.0)
        return max(0.1, min(10.0, raw))
    except (TypeError, ValueError):
        return 1.0


def get_defense_factory_level(player_id: int, planet_id: int, *, conn=None) -> int:
    return defense_factory_level_for_planet(int(planet_id), conn=conn)


def defense_factory_level_for_planet(planet_id: int, *, conn=None) -> int:
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    return max(0, int(buildings.get("defense_factory") or 0))


def _effective_build_seconds(
    defense_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
    build_time_speed: float | None = None,
) -> int:
    """Per-unit build time — scaled by Orbital Shipyard level (shared with shipyard)."""
    spec = get_defense(defense_key)
    if not spec:
        return 0
    base = max(1, int(spec.get("build_seconds") or 1))
    lvl = max(1, int(shipyard_level or 1))
    from .shipyard import production_level_cycle_seconds

    seconds = production_level_cycle_seconds(
        base,
        lvl,
        level_factor=BUILD_TIME_LEVEL_FACTOR,
    )
    speed = (
        max(0.000001, float(build_time_speed))
        if build_time_speed is not None
        else _defense_speed_multiplier(conn=conn)
    )
    if planet_id and conn:
        from .shipyard import _directive_time_speed

        speed *= _directive_time_speed(planet_id, "defense_time_speed", conn=conn)
    return max(1, int(math.ceil(seconds / speed)))


def unit_build_seconds(
    defense_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
    build_time_speed: float | None = None,
) -> int:
    return _effective_build_seconds(
        defense_key,
        shipyard_level,
        conn=conn,
        planet_id=planet_id,
        build_time_speed=build_time_speed,
    )


def base_unit_seconds_for_defense(defense_key: str) -> int:
    spec = get_defense(defense_key) or {}
    return max(1, int(spec.get("build_seconds") or 1))


def _batch_capacity_for_defense(defense_key: str, shipyard_level: int) -> int:
    from .shipyard import orbital_production_batch_capacity

    _ = defense_key
    return orbital_production_batch_capacity(shipyard_level)


def _production_shipyard_level(planet_id: int, *, conn) -> int:
    from .shipyard import shipyard_level_for_planet

    return max(1, int(shipyard_level_for_planet(int(planet_id), conn=conn) or 1))


def _check_defense_requirements(
    defense_key: str,
    *,
    buildings: Mapping[str, Any],
    research: Mapping[str, Any],
) -> Tuple[bool, List[str]]:
    spec = get_defense(defense_key)
    if not spec:
        return False, ["defense_not_found"]
    req = spec.get("requirements") or {}
    missing: List[str] = []
    for bkey, need in (req.get("buildings") or {}).items():
        have = int(buildings.get(str(bkey), 0) or 0)
        if have < int(need):
            missing.append(f"defense_req_building_{bkey}_{need}")
    for rkey, need in (req.get("research") or {}).items():
        have = int(research.get(str(rkey), 0) or 0)
        if have < int(need):
            missing.append(f"defense_req_research_{rkey}_{need}")
    return (len(missing) == 0), missing


def defense_unlocked(
    defense_key: str,
    factory_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
) -> bool:
    spec = get_defense(defense_key)
    if not spec:
        return False
    need = int(spec.get("required_defense_factory_level") or 99)
    if int(factory_level) < need:
        return False
    if player_id is not None and planet_id is not None:
        building_levels = (
            buildings
            if buildings is not None
            else get_planet_buildings(int(planet_id), conn=conn)
        )
        research_levels = (
            research
            if research is not None
            else get_research_levels(user_id=int(player_id), conn=conn)
        )
        ok, _ = _check_defense_requirements(
            defense_key,
            buildings=building_levels,
            research=research_levels,
        )
        return ok
    return True


def _job_duration_seconds(
    defense_key: str,
    amount: int,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
) -> int:
    from .shipyard import production_job_duration_seconds

    unit = unit_build_seconds(
        defense_key, shipyard_level, conn=conn, planet_id=planet_id
    )
    cap = _batch_capacity_for_defense(defense_key, shipyard_level)
    return production_job_duration_seconds(
        unit_seconds=unit, amount=int(amount), batch_capacity=cap
    )


def _job_scheduled_duration_seconds(row: Mapping[str, Any]) -> int:
    started = float(row.get("started_at") or 0)
    finish = float(row.get("finish_at") or 0)
    return max(1, int(finish - started))


def _job_total_units(row: Mapping[str, Any], shipyard_level: int, *, conn) -> int:
    from .shipyard import production_infer_total_units

    dk = str(row["defense_key"])
    remaining = max(0, int(row.get("amount") or 0))
    unit_sec = unit_build_seconds(dk, shipyard_level, conn=conn)
    cap = _batch_capacity_for_defense(dk, shipyard_level)
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
    from .queue_poll import DUE_TIME_EPSILON_SEC
    from .shipyard import production_progressive_units_to_deliver

    remaining = max(0, int(row.get("amount") or 0))
    if remaining <= 0:
        return 0

    dk = str(row["defense_key"])
    unit_sec = unit_build_seconds(dk, shipyard_level, conn=conn)
    cap = _batch_capacity_for_defense(dk, shipyard_level)
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


def list_defense_queue_rows(planet_id: int, *, conn) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM defense_queue
        WHERE planet_id = ? AND status = ?
        ORDER BY queue_position ASC, id ASC;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    return [dict(r) for r in cur.fetchall()]


def _renumber_positions(conn, planet_id: int) -> None:
    rows = list_defense_queue_rows(planet_id, conn=conn)
    cur = conn.cursor()
    for idx, row in enumerate(rows):
        cur.execute(
            "UPDATE defense_queue SET queue_position = ? WHERE id = ?;",
            (idx, int(row["id"])),
        )


def recalculate_queue_finish_times(
    planet_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    sy_level = _production_shipyard_level(planet_id, conn=conn)
    ts = float(now if now is not None else _now())
    rows = list_defense_queue_rows(planet_id, conn=conn)
    cursor = conn.cursor()
    schedule_at = ts
    for row in rows:
        dk = str(row["defense_key"])
        amt = int(row["amount"] or 1)
        duration = _job_duration_seconds(
            dk, amt, sy_level, conn=conn, planet_id=int(planet_id)
        )
        started = schedule_at
        finish = schedule_at + duration
        cursor.execute(
            """
            UPDATE defense_queue
            SET started_at = ?, finish_at = ?
            WHERE id = ?;
            """,
            (started, finish, int(row["id"])),
        )
        schedule_at = finish


def sync_defense_queue_finish_times(
    planet_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    """Align finish_at with live batch remaining; preserve head started_at when params match."""
    from .shipyard import (
        production_live_order_remaining_seconds,
        production_schedule_matches_live_params,
    )

    if not defense_queue_table_ready(conn):
        return
    sy_level = _production_shipyard_level(planet_id, conn=conn)
    ts = float(now if now is not None else _now())
    rows = list_defense_queue_rows(planet_id, conn=conn)
    if not rows:
        return

    cur = conn.cursor()
    head = rows[0]
    rem = max(0, int(head.get("amount") or 0))
    if rem > 0:
        dk = str(head["defense_key"])
        unit = unit_build_seconds(dk, sy_level, conn=conn, planet_id=int(planet_id))
        cap = _batch_capacity_for_defense(dk, sy_level)
        scheduled = _job_scheduled_duration_seconds(head)
        total_guess = _job_total_units(head, sy_level, conn=conn)
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
                    "UPDATE defense_queue SET finish_at = ? WHERE id = ?;",
                    (new_finish, int(head["id"])),
                )
            else:
                cur.execute(
                    """
                    UPDATE defense_queue
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
        dk = str(row["defense_key"])
        amt = max(1, int(row.get("amount") or 1))
        duration = _job_duration_seconds(
            dk, amt, sy_level, conn=conn, planet_id=int(planet_id)
        )
        started = schedule_at
        finish = schedule_at + duration
        cur.execute(
            """
            UPDATE defense_queue
            SET started_at = ?, finish_at = ?
            WHERE id = ?;
            """,
            (started, finish, int(row["id"])),
        )
        schedule_at = finish


def queue_count(planet_id: int, *, conn) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM defense_queue
        WHERE planet_id = ? AND status = ?;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    row = cur.fetchone()
    return int(row["c"] if row else 0)


def planet_ids_with_defense_queue(
    planet_ids: Sequence[int],
    conn=None,
    *,
    now: Optional[float] = None,
) -> set[int]:
    """
    GC-PLANET-UI-001: DISTINCT planet_ids with at least one queued defense job
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
        if not defense_schema_ready(conn) or not defense_queue_table_ready(conn):
            return set()
        ts = float(time.time() if now is None else now)
        placeholders = ",".join("?" for _ in ids)
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT DISTINCT planet_id
            FROM defense_queue
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


def enqueue_defense_build(
    *,
    player_id: int,
    planet_id: int,
    defense_key: str,
    amount: int,
    cost: Mapping[str, int],
    conn,
) -> Tuple[bool, str, int | None]:
    from .options import vacation_blocks_outbound

    ok_vacation, vac_reason = vacation_blocks_outbound(int(player_id), conn=conn)
    if not ok_vacation:
        return False, vac_reason, None
    if not defense_queue_table_ready(conn):
        return False, "defense_unavailable", None
    if queue_count(planet_id, conn=conn) >= get_defense_queue_limit(conn=conn):
        return False, "queue_full", None

    dk = str(defense_key or "").strip()
    qty = max(1, int(amount))
    now = _now()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COALESCE(MAX(queue_position), -1) + 1 AS next_pos
        FROM defense_queue
        WHERE planet_id = ? AND status = ?;
        """,
        (int(planet_id), QUEUE_STATUS_QUEUED),
    )
    next_pos = int(cur.fetchone()["next_pos"] or 0)

    exact_metal = max(0, int(cost.get("metal") or 0))
    exact_crystal = max(0, int(cost.get("crystal") or 0))
    exact_fuel = max(0, int(cost.get("fuel_cells") or 0))
    cur.execute(
        """
        INSERT INTO defense_queue (
            player_id, planet_id, defense_key, amount, status,
            started_at, finish_at, created_at,
            queue_position,
            cost_metal, cost_crystal, cost_fuel_cells,
            cost_metal_exact, cost_crystal_exact, cost_fuel_cells_exact
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(player_id),
            int(planet_id),
            dk,
            qty,
            QUEUE_STATUS_QUEUED,
            now,
            now,
            now,
            next_pos,
            _legacy_i64_cost_snapshot(exact_metal),
            _legacy_i64_cost_snapshot(exact_crystal),
            _legacy_i64_cost_snapshot(exact_fuel),
            str(exact_metal),
            str(exact_crystal),
            str(exact_fuel),
        ),
    )
    job_id = int(cur.lastrowid)
    recalculate_queue_finish_times(planet_id, conn=conn, now=now)
    return True, "", job_id


def finish_due_defense_jobs_for_planet(
    conn,
    planet_id: int,
    player_id: int,
    *,
    now: Optional[float] = None,
) -> int:
    return _finish_due_defense_jobs_impl(
        conn,
        int(planet_id),
        int(player_id),
        now=float(now if now is not None else _now()),
    )


def _finish_due_defense_jobs_impl(
    conn,
    planet_id: int,
    player_id: int,
    *,
    now: float,
) -> int:
    if not defense_queue_table_ready(conn) or not defense_schema_ready(conn):
        return 0

    ts = float(now)
    rows = list_defense_queue_rows(planet_id, conn=conn)
    if not rows:
        return 0

    sy_level = _production_shipyard_level(planet_id, conn=conn)
    completed_jobs = 0
    cur = conn.cursor()

    while rows:
        head = rows[0]
        remaining_amt = max(0, int(head.get("amount") or 0))
        if remaining_amt <= 0:
            cur.execute("DELETE FROM defense_queue WHERE id = ?;", (int(head["id"]),))
            try:
                from .activity_xp import SOURCE_DEFENSE_FINISH, grant_queue_job_activity_xp

                grant_queue_job_activity_xp(
                    int(player_id),
                    int(planet_id),
                    SOURCE_DEFENSE_FINISH,
                    int(head["id"]),
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "activity_xp defense grant failed player=%s job=%s",
                    player_id,
                    head["id"],
                )
            completed_jobs += 1
            rows = list_defense_queue_rows(planet_id, conn=conn)
            continue

        to_deliver = progressive_units_to_deliver(head, sy_level, now=ts, conn=conn)
        finish_at = float(head.get("finish_at") or 0)
        if to_deliver <= 0 and remaining_amt > 0 and finish_at > 0 and ts + 0.001 >= finish_at:
            to_deliver = remaining_amt
        if to_deliver <= 0:
            break

        dk = str(head["defense_key"])
        if is_known_defense_key(dk):
            add_planet_defense(int(planet_id), {dk: to_deliver}, conn=conn)
            try:
                from .directives.progress import emit_defense_built_events

                emit_defense_built_events(
                    int(player_id),
                    defense_key=dk,
                    amount=to_deliver,
                    job_id=int(head["id"]),
                    delivered_before=max(0, int(head.get("amount") or 0)),
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "imperial_directives defense progress failed player=%s",
                    player_id,
                )

        remaining = max(0, int(head["amount"] or 0) - to_deliver)
        if remaining <= 0:
            cur.execute("DELETE FROM defense_queue WHERE id = ?;", (int(head["id"]),))
            try:
                from .activity_xp import SOURCE_DEFENSE_FINISH, grant_queue_job_activity_xp

                grant_queue_job_activity_xp(
                    int(player_id),
                    int(planet_id),
                    SOURCE_DEFENSE_FINISH,
                    int(head["id"]),
                    conn=conn,
                    now=ts,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "activity_xp defense grant failed player=%s job=%s",
                    player_id,
                    head["id"],
                )
            completed_jobs += 1
            rows = list_defense_queue_rows(planet_id, conn=conn)
            continue

        cur.execute(
            "UPDATE defense_queue SET amount = ? WHERE id = ?;",
            (remaining, int(head["id"])),
        )
        sync_defense_queue_finish_times(planet_id, conn=conn, now=ts)
        break

    if completed_jobs:
        _renumber_positions(conn, planet_id)
        recalculate_queue_finish_times(planet_id, conn=conn, now=ts)

    return completed_jobs


def _planet_resources(planet_id: int, *, conn) -> Tuple[int, int, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return 0, 0, 0
    return (
        int(row["metal"] or 0),
        int(row["crystal"] or 0),
        int(row["fuel_cells"] or 0),
    )


def _try_spend_build_resources(
    conn,
    planet_id: int,
    *,
    metal: int,
    crystal: int,
    fuel_cells: int = 0,
) -> bool:
    if metal < 0 or crystal < 0 or fuel_cells < 0:
        raise ValueError("Costs must be >= 0")
    if metal == 0 and crystal == 0 and fuel_cells == 0:
        return True
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal - ?,
            crystal = crystal - ?,
            fuel_cells = fuel_cells - ?
        WHERE id = ?
          AND metal >= ?
          AND crystal >= ?
          AND fuel_cells >= ?;
        """,
        (
            resource_db_param(metal),
            resource_db_param(crystal),
            resource_db_param(fuel_cells),
            int(planet_id),
            resource_db_param(metal),
            resource_db_param(crystal),
            resource_db_param(fuel_cells),
        ),
    )
    return cur.rowcount == 1


def max_build_amount_for_planet(
    metal_have: float,
    crystal_have: float,
    fuel_have: float,
    defense_key: str,
    factory_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
) -> int:
    dk = str(defense_key or "").strip()
    if not defense_unlocked(
        dk,
        factory_level,
        player_id=player_id,
        planet_id=planet_id,
        conn=conn,
        buildings=buildings,
        research=research,
    ):
        return 0
    cost = unit_build_cost(dk)
    if cost["metal"] <= 0 and cost["crystal"] <= 0 and cost["fuel_cells"] <= 0:
        return 0
    limits: List[int] = []
    if cost["metal"] > 0:
        limits.append(int(metal_have) // cost["metal"])
    if cost["crystal"] > 0:
        limits.append(int(crystal_have) // cost["crystal"])
    if cost["fuel_cells"] > 0:
        limits.append(int(fuel_have) // cost["fuel_cells"])
    if not limits:
        return 0
    return max(0, min(limits))


def can_build_defense(
    player_id: int,
    planet_id: int,
    defense_key: str,
    amount: int,
    *,
    conn=None,
) -> Tuple[bool, str]:
    dk = str(defense_key or "").strip()
    if not is_known_defense_key(dk) or dk not in DEFENSES:
        return False, "unknown_defense"
    from .number_format import parse_int_number

    qty = parse_int_number(amount, default=0)
    if qty <= 0:
        return False, "invalid_amount"

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            return False, "planet_not_found"

        factory_level = get_defense_factory_level(player_id, planet_id, conn=conn)
        if factory_level <= 0:
            return False, "defense_factory_required"
        need_df = int((get_defense(dk) or {}).get("required_defense_factory_level") or 99)
        if factory_level < need_df:
            return False, "defense_factory_level_too_low"
        if not defense_unlocked(
            dk, factory_level, player_id=player_id, planet_id=planet_id, conn=conn
        ):
            return False, "requirements"

        if defense_queue_table_ready(conn) and queue_count(planet_id, conn=conn) >= get_defense_queue_limit(
            conn=conn
        ):
            return False, "queue_full"

        metal, crystal, fuel = _planet_resources(planet_id, conn=conn)
        max_qty = max_build_amount_for_planet(
            metal,
            crystal,
            fuel,
            dk,
            factory_level,
            player_id=player_id,
            planet_id=planet_id,
            conn=conn,
        )
        if qty > max_qty:
            return False, "not_enough_resources"
        return True, ""
    finally:
        if own and conn is not None:
            conn.close()


def build_defense(
    *,
    player_id: int,
    planet_id: int,
    defense_key: str,
    amount: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    dk = str(defense_key or "").strip()
    ok_check, reason = can_build_defense(player_id, planet_id, dk, amount, conn=conn)
    if not ok_check:
        return False, reason, None

    from .number_format import parse_int_number

    qty = parse_int_number(amount, default=0)
    if qty <= 0:
        return False, "invalid_amount", None
    unit = unit_build_cost(dk)
    total_m = unit["metal"] * qty
    total_c = unit["crystal"] * qty
    total_f = unit["fuel_cells"] * qty

    own = conn is None
    if own:
        conn = db()
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))

        if not _try_spend_build_resources(
            conn, int(planet_id), metal=total_m, crystal=total_c, fuel_cells=total_f
        ):
            if own or began_tx:
                rollback(conn)
            return False, "not_enough_resources", None

        if not defense_schema_ready(conn) or not defense_queue_table_ready(conn):
            if own or began_tx:
                rollback(conn)
            return False, "defense_unavailable", None

        factory_level = get_defense_factory_level(player_id, planet_id, conn=conn)
        ok_q, reason_q, job_id = enqueue_defense_build(
            player_id=int(player_id),
            planet_id=int(planet_id),
            defense_key=dk,
            amount=qty,
            cost={"metal": total_m, "crystal": total_c, "fuel_cells": total_f},
            conn=conn,
        )
        if not ok_q:
            if own or began_tx:
                rollback(conn)
            return False, reason_q or "queue_full", None

        if own or began_tx:
            commit(conn)

        payload = build_defense_api_payload(int(player_id), int(planet_id), conn=conn)
        payload["defense_key"] = dk
        payload["amount"] = qty
        payload["job_id"] = job_id
        payload["cost"] = {"metal": total_m, "crystal": total_c, "fuel_cells": total_f}
        return True, "", payload
    except Exception:
        if own or began_tx:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def _next_unit_finish_at(
    row: Mapping[str, Any], shipyard_level: int, *, conn
) -> float:
    from .shipyard import production_next_batch_finish_at

    dk = str(row["defense_key"])
    started = float(row.get("started_at") or 0)
    unit_sec = unit_build_seconds(dk, shipyard_level, conn=conn)
    cap = _batch_capacity_for_defense(dk, shipyard_level)
    total = _job_total_units(row, shipyard_level, conn=conn)
    remaining = max(0, int(row.get("amount") or 0))
    delivered = max(0, total - remaining)
    return production_next_batch_finish_at(
        started_at=started,
        delivered=delivered,
        unit_seconds=unit_sec,
        batch_capacity=cap,
    )


def _defense_job_row_for_client(
    row: Mapping[str, Any],
    *,
    idx: int,
    shipyard_level: int,
    now: float,
    conn,
) -> Dict[str, Any]:
    from .defense_defs import defense_icon_static_path
    from .shipyard import production_live_order_remaining_seconds

    dk = str(row["defense_key"])
    amount_remaining = max(0, int(row.get("amount") or 0))
    total_units = _job_total_units(row, shipyard_level, conn=conn)
    units_delivered = max(0, total_units - amount_remaining)
    unit_sec = unit_build_seconds(dk, shipyard_level, conn=conn)
    finish_at = float(row.get("finish_at") or 0)
    is_active = idx == 0
    started_at = float(row.get("started_at") or 0)
    cap = _batch_capacity_for_defense(dk, shipyard_level)

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
        order_total_seconds = max(
            1,
            int(finish_at - started_at) if started_at > 0 else order_remaining,
        )
        next_finish_at = _next_unit_finish_at(row, shipyard_level, conn=conn)
    else:
        order_remaining = max(0, int(finish_at - now))
        order_total_seconds = _job_scheduled_duration_seconds(row)
        next_finish_at = finish_at

    start_at = started_at if is_active and started_at > 0 else max(0.0, finish_at - order_total_seconds)

    return {
        "id": int(row["id"]),
        "defense_key": dk,
        "start_at": start_at,
        "started_at": started_at,
        "icon": defense_icon_static_path(dk),
        # Display / mini-queue use remaining units still in this job (not original total).
        "amount": amount_remaining,
        "amount_total": total_units,
        "amount_remaining": amount_remaining,
        "units_delivered": units_delivered,
        "unit_seconds": unit_sec,
        "next_finish_at": next_finish_at,
        "finish_at": finish_at,
        "remaining": order_remaining,
        "order_remaining": order_remaining,
        "order_total_seconds": order_total_seconds,
        "total_seconds": max(1, order_total_seconds),
        "queue_position": int(row.get("queue_position") or idx),
        "is_active": is_active,
        "cost_metal": stored_cost_int(row, "metal"),
        "cost_crystal": stored_cost_int(row, "crystal"),
        "cost_fuel_cells": stored_cost_int(row, "fuel_cells"),
    }


def defense_queue_for_client(
    player_id: int,
    planet_id: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    sy_level = _production_shipyard_level(planet_id, conn=conn)
    ts = float(now if now is not None else _now())
    if defense_queue_table_ready(conn):
        finish_due_defense_jobs_for_planet(conn, int(planet_id), int(player_id), now=ts)
        sync_defense_queue_finish_times(int(planet_id), conn=conn, now=ts)

    rows = list_defense_queue_rows(planet_id, conn=conn) if defense_queue_table_ready(conn) else []
    jobs: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        jobs.append(
            _defense_job_row_for_client(
                row,
                idx=idx,
                shipyard_level=sy_level,
                now=ts,
                conn=conn,
            )
        )

    first_remaining = jobs[0]["remaining"] if jobs else 0
    summary = {
        "count": len(jobs),
        "limit": get_defense_queue_limit(conn=conn),
        "first_finish_in": first_remaining,
    }
    summary.update(refund_summary_percents())
    return {
        "queue": jobs,
        "summary": summary,
    }


def build_defense_api_payload(
    player_id: int,
    planet_id: int,
    *,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
    stock: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        # GC-PERF-DEFENSE-SSR-006: one shared building/research/stock snapshot
        # for the full catalog. The old path reloaded Buildings + Research via
        # defense_unlocked/max_build_amount once or twice per defense row.
        from .defense_defs import defense_icon_static_path
        from .models import get_planet_buildings, get_research_levels
        from .shipyard import shipyard_level_from_buildings
        from .technical_data import apply_combat_stats_to_catalog_entry, resolve_unit_effect_context

        building_levels = (
            buildings
            if buildings is not None
            else get_planet_buildings(int(planet_id), conn=conn)
        )
        research_levels = (
            research
            if research is not None
            else get_research_levels(user_id=int(player_id), conn=conn)
        )
        defense_stock = (
            stock
            if stock is not None
            else get_planet_defense(int(planet_id), conn=conn)
        )
        factory_level = max(0, int(building_levels.get("defense_factory") or 0))
        sy_level = shipyard_level_from_buildings(building_levels)
        metal, crystal, fuel = _planet_resources(planet_id, conn=conn)
        buildable: List[Dict[str, Any]] = []
        queue_full = False
        if defense_queue_table_ready(conn):
            queue_full = queue_count(planet_id, conn=conn) >= get_defense_queue_limit(conn=conn)
        defense_build_speed = _defense_speed_multiplier(conn=conn)
        try:
            from .planet_evolution.repository import get_context_planet

            planet_row = get_context_planet(int(player_id), conn=conn)
        except Exception:
            planet_row = None
        effect_ctx = resolve_unit_effect_context(
            buildings=building_levels,
            research_levels=research_levels,
            player_id=int(player_id),
            conn=conn,
            planet=planet_row,
        )

        for key in sorted(ACTIVE_DEFENSE_KEYS):
            if not defense_unlocked(
                key,
                factory_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                buildings=building_levels,
                research=research_levels,
            ):
                continue
            cost = unit_build_cost(key)
            max_qty = max_build_amount_for_planet(
                metal,
                crystal,
                fuel,
                key,
                factory_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                buildings=building_levels,
                research=research_levels,
            )
            can_build = not queue_full and max_qty > 0
            block_reason = ""
            if queue_full:
                block_reason = "queue_full"
            elif max_qty <= 0:
                block_reason = "not_enough_resources"
            from .combat_models import combat_stats_for_defense

            stats = combat_stats_for_defense(key)
            spec = get_defense(key) or {}
            entry = {
                    "defense_key": key,
                    "name_key": str(spec.get("name_key") or f"defense_{key}"),
                    "description_key": str(spec.get("description_key") or f"defense_{key}_desc"),
                    "role": str(spec.get("role") or "turret"),
                    "attack": int(stats.attack if stats else spec.get("attack", 0) or 0),
                    "shield": int(stats.shield if stats else spec.get("shield", 0) or 0),
                    "hull": int(stats.hull if stats else spec.get("hull", 0) or 0),
                    "icon": defense_icon_static_path(key),
                    "required_defense_factory_level": int(
                        (get_defense(key) or {}).get("required_defense_factory_level") or 99
                    ),
                    "cost_metal": cost["metal"],
                    "cost_crystal": cost["crystal"],
                    "cost_fuel_cells": cost["fuel_cells"],
                    "build_seconds": unit_build_seconds(
                        key,
                        sy_level,
                        conn=conn,
                        build_time_speed=defense_build_speed,
                    ),
                    "effective_batch_capacity": _batch_capacity_for_defense(key, sy_level),
                    "max_build": max_qty,
                    "stock": int(defense_stock.get(key, 0) or 0),
                    "can_build": can_build,
                    "block_reason": block_reason,
                }
            apply_combat_stats_to_catalog_entry(entry, effect_ctx=effect_ctx)
            buildable.append(entry)
        queue = defense_queue_for_client(
            player_id, planet_id, conn=conn
        )
        from .queue_card import (
            enrich_mini_queue_jobs_batch_size,
            group_card_jobs_by_owner_key,
            map_card_jobs_to_mini_queue_jobs,
            map_defense_queue_to_card_jobs,
        )

        card_jobs = map_defense_queue_to_card_jobs(queue)
        by_owner = group_card_jobs_by_owner_key(card_jobs)
        queue["card_jobs_by_owner"] = by_owner
        queue["mini_queue_jobs"] = enrich_mini_queue_jobs_batch_size(
            map_card_jobs_to_mini_queue_jobs(card_jobs, domain="defense"),
            domain="defense",
            shipyard_level=sy_level,
        )
        from .shipyard import orbital_production_batch_capacity

        return {
            "defense_factory_level": factory_level,
            "orbital_shipyard_level": sy_level,
            "production_batch_capacity": orbital_production_batch_capacity(sy_level),
            "buildable_defense": buildable,
            "current_defense": defense_stock,
            "defense_queue": queue,
            "resources": {
                "metal": int(metal),
                "crystal": int(crystal),
                "fuel_cells": int(fuel),
            },
        }
    finally:
        if own and conn is not None:
            conn.close()


def _attach_queue_jobs_to_defense_rows(
    rows: List[Dict[str, Any]],
    jobs_by_key: Mapping[str, Any],
) -> None:
    """GC-536 — optional queue_job on each defense catalog row (presentation only)."""
    from .queue_card import card_queue_job_for_item

    for row in rows:
        owner_key = str(row.get("defense_key") or "")
        qj = card_queue_job_for_item(jobs_by_key, owner_key) if owner_key else None
        if qj:
            row["queue_job"] = dict(qj)
        elif "queue_job" in row:
            del row["queue_job"]


def defense_combat_priority(defense_key: str) -> int:
    spec = get_defense(str(defense_key)) or {}
    return (
        int(spec.get("attack") or 0)
        + int(spec.get("shield") or 0)
        + int(spec.get("hull") or 0)
    )


def summarize_defense_stock(stock: Mapping[str, int]) -> Dict[str, int]:
    """Aggregate defense count and combat power from a stock map."""
    total_units = 0
    defense_power = 0
    shield_power = 0
    for key, qty in stock.items():
        count = int(qty or 0)
        if count <= 0 or not is_known_defense_key(str(key)):
            continue
        spec = get_defense(str(key)) or {}
        total_units += count
        defense_power += int(spec.get("attack") or 0) * count
        shield_power += int(spec.get("shield") or 0) * count
    return {
        "total_units": total_units,
        "defense_power": defense_power,
        "shield_power": shield_power,
    }


def get_planet_defense_intel(planet_id: int, *, conn) -> Dict[str, Any]:
    """Planet defense stock + power totals for spy snapshots."""
    if not defense_schema_ready(conn):
        return {
            "stock": {},
            "total_units": 0,
            "defense_power": 0,
            "shield_power": 0,
        }
    stock = get_planet_defense(int(planet_id), conn=conn)
    totals = summarize_defense_stock(stock)
    return {"stock": stock, **totals}
