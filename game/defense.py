"""Planet-scoped defense build queue — costs upfront, delivery via queue_engine."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import begin_write_transaction, commit, db, in_transaction, rollback, table_exists
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
    lock_planet_for_update,
)

MAX_DEFENSE_QUEUE = 3
QUEUE_STATUS_QUEUED = "queued"
BUILD_TIME_LEVEL_FACTOR = 0.90


def _now() -> float:
    return time.time()


def defense_queue_table_ready(conn) -> bool:
    if not table_exists(conn, "defense_queue"):
        return False
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(defense_queue);")
    cols = {str(r[1]) for r in cur.fetchall()}
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


def _effective_build_seconds(defense_key: str, factory_level: int, *, conn=None) -> int:
    spec = get_defense(defense_key)
    if not spec:
        return 0
    base = max(1, int(spec.get("build_seconds") or 1))
    lvl = max(1, int(factory_level or 1))
    seconds = max(1, int(math.ceil(base * (BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)))))
    speed = _defense_speed_multiplier(conn=conn)
    return max(1, int(math.ceil(seconds / speed)))


def unit_build_seconds(defense_key: str, factory_level: int, *, conn=None) -> int:
    return _effective_build_seconds(defense_key, factory_level, conn=conn)


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
) -> bool:
    spec = get_defense(defense_key)
    if not spec:
        return False
    need = int(spec.get("required_defense_factory_level") or 99)
    if int(factory_level) < need:
        return False
    if player_id is not None and planet_id is not None:
        buildings = get_planet_buildings(int(planet_id), conn=conn)
        research = get_research_levels(user_id=int(player_id), conn=conn)
        ok, _ = _check_defense_requirements(defense_key, buildings=buildings, research=research)
        return ok
    return True


def _job_duration_seconds(
    defense_key: str, amount: int, factory_level: int, *, conn=None
) -> int:
    unit = unit_build_seconds(defense_key, factory_level, conn=conn)
    return max(1, unit * max(1, int(amount)))


def _job_scheduled_duration_seconds(row: Mapping[str, Any]) -> int:
    started = float(row.get("started_at") or 0)
    finish = float(row.get("finish_at") or 0)
    return max(1, int(finish - started))


def _job_total_units(row: Mapping[str, Any], factory_level: int, *, conn) -> int:
    dk = str(row["defense_key"])
    remaining = max(0, int(row.get("amount") or 0))
    unit_sec = unit_build_seconds(dk, factory_level, conn=conn)
    scheduled = max(1, int(round(_job_scheduled_duration_seconds(row) / unit_sec)))
    return max(remaining, scheduled)


def _units_elapsed_for_job(
    row: Mapping[str, Any],
    factory_level: int,
    *,
    now: float,
    conn,
) -> int:
    from .queue_poll import DUE_TIME_EPSILON_SEC

    dk = str(row["defense_key"])
    started = float(row.get("started_at") or 0)
    unit_sec = unit_build_seconds(dk, factory_level, conn=conn)
    total = _job_total_units(row, factory_level, conn=conn)
    elapsed = float(now) + float(DUE_TIME_EPSILON_SEC) - started
    if elapsed < unit_sec:
        return 0
    return min(total, int(elapsed // unit_sec))


def progressive_units_to_deliver(
    row: Mapping[str, Any],
    factory_level: int,
    *,
    now: float,
    conn,
) -> int:
    remaining = max(0, int(row.get("amount") or 0))
    if remaining <= 0:
        return 0

    from .queue_poll import DUE_TIME_EPSILON_SEC

    finish = float(row.get("finish_at") or 0)
    if float(now) + float(DUE_TIME_EPSILON_SEC) >= finish:
        return remaining

    total = _job_total_units(row, factory_level, conn=conn)
    already_delivered = total - remaining
    units_elapsed = _units_elapsed_for_job(row, factory_level, now=now, conn=conn)
    return max(0, min(remaining, units_elapsed - already_delivered))


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
    factory_level: int,
    *,
    conn,
    now: Optional[float] = None,
) -> None:
    ts = float(now if now is not None else _now())
    rows = list_defense_queue_rows(planet_id, conn=conn)
    cursor = conn.cursor()
    schedule_at = ts
    for row in rows:
        dk = str(row["defense_key"])
        amt = int(row["amount"] or 1)
        duration = _job_duration_seconds(dk, amt, factory_level, conn=conn)
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


def enqueue_defense_build(
    *,
    player_id: int,
    planet_id: int,
    defense_key: str,
    amount: int,
    factory_level: int,
    cost: Mapping[str, int],
    conn,
) -> Tuple[bool, str, int | None]:
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

    cur.execute(
        """
        INSERT INTO defense_queue (
            player_id, planet_id, defense_key, amount, status,
            started_at, finish_at, created_at,
            queue_position, cost_metal, cost_crystal
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
            int(cost.get("metal") or 0),
            int(cost.get("crystal") or 0),
        ),
    )
    job_id = int(cur.lastrowid)
    recalculate_queue_finish_times(planet_id, factory_level, conn=conn, now=now)
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

    factory_level = defense_factory_level_for_planet(planet_id, conn=conn)
    completed_jobs = 0
    cur = conn.cursor()

    while rows:
        head = rows[0]
        to_deliver = progressive_units_to_deliver(head, factory_level, now=ts, conn=conn)
        if to_deliver <= 0:
            break

        dk = str(head["defense_key"])
        if is_known_defense_key(dk):
            add_planet_defense(int(planet_id), {dk: to_deliver}, conn=conn)
            try:
                from .score_events import apply_score_updates_for_players

                apply_score_updates_for_players(
                    [int(player_id)],
                    conn=conn,
                    recalc_ranks=False,
                )
            except Exception:
                pass

        remaining = max(0, int(head["amount"] or 0) - to_deliver)
        if remaining <= 0:
            cur.execute("DELETE FROM defense_queue WHERE id = ?;", (int(head["id"]),))
            completed_jobs += 1
            rows = list_defense_queue_rows(planet_id, conn=conn)
            continue

        cur.execute(
            "UPDATE defense_queue SET amount = ? WHERE id = ?;",
            (remaining, int(head["id"])),
        )
        break

    if completed_jobs:
        _renumber_positions(conn, planet_id)
        recalculate_queue_finish_times(planet_id, factory_level, conn=conn, now=ts)

    return completed_jobs


def _planet_resources(planet_id: int, *, conn) -> Tuple[float, float]:
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return 0.0, 0.0
    return float(row["metal"] or 0), float(row["crystal"] or 0)


def _try_spend_build_resources(
    conn,
    planet_id: int,
    *,
    metal: int,
    crystal: int,
) -> bool:
    if metal < 0 or crystal < 0:
        raise ValueError("Costs must be >= 0")
    if metal == 0 and crystal == 0:
        return True
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal - ?,
            crystal = crystal - ?
        WHERE id = ?
          AND metal >= ?
          AND crystal >= ?;
        """,
        (int(metal), int(crystal), int(planet_id), int(metal), int(crystal)),
    )
    return cur.rowcount == 1


def max_build_amount_for_planet(
    metal_have: float,
    crystal_have: float,
    defense_key: str,
    factory_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
) -> int:
    dk = str(defense_key or "").strip()
    if not defense_unlocked(
        dk, factory_level, player_id=player_id, planet_id=planet_id, conn=conn
    ):
        return 0
    cost = unit_build_cost(dk)
    if cost["metal"] <= 0 and cost["crystal"] <= 0:
        return 0
    limits: List[int] = []
    if cost["metal"] > 0:
        limits.append(int(metal_have) // cost["metal"])
    else:
        limits.append(999999)
    if cost["crystal"] > 0:
        limits.append(int(crystal_have) // cost["crystal"])
    else:
        limits.append(999999)
    return max(0, min(limits) if limits else 0)


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
    try:
        qty = int(amount)
    except (TypeError, ValueError):
        return False, "invalid_amount"
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

        metal, crystal = _planet_resources(planet_id, conn=conn)
        max_qty = max_build_amount_for_planet(
            metal,
            crystal,
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

    qty = int(amount)
    unit = unit_build_cost(dk)
    total_m = unit["metal"] * qty
    total_c = unit["crystal"] * qty

    own = conn is None
    if own:
        conn = db()
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))

        if not _try_spend_build_resources(conn, int(planet_id), metal=total_m, crystal=total_c):
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
            factory_level=factory_level,
            cost={"metal": total_m, "crystal": total_c},
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
        payload["cost"] = {"metal": total_m, "crystal": total_c}
        return True, "", payload
    except Exception:
        if own or began_tx:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def _next_unit_finish_at(
    row: Mapping[str, Any], factory_level: int, *, conn
) -> float:
    dk = str(row["defense_key"])
    started = float(row.get("started_at") or 0)
    unit_sec = unit_build_seconds(dk, factory_level, conn=conn)
    total = _job_total_units(row, factory_level, conn=conn)
    remaining = max(0, int(row.get("amount") or 0))
    delivered = max(0, total - remaining)
    return started + (delivered + 1) * unit_sec


def _defense_job_row_for_client(
    row: Mapping[str, Any],
    *,
    idx: int,
    factory_level: int,
    now: float,
    conn,
) -> Dict[str, Any]:
    from .defense_defs import defense_icon_static_path

    dk = str(row["defense_key"])
    amount_remaining = max(0, int(row.get("amount") or 0))
    total_units = _job_total_units(row, factory_level, conn=conn)
    units_delivered = max(0, total_units - amount_remaining)
    unit_sec = unit_build_seconds(dk, factory_level, conn=conn)
    finish_at = float(row.get("finish_at") or 0)
    order_total_seconds = _job_scheduled_duration_seconds(row)
    is_active = idx == 0
    order_remaining = max(0, int(finish_at - now))
    next_finish_at = _next_unit_finish_at(row, factory_level, conn=conn) if is_active else finish_at

    return {
        "id": int(row["id"]),
        "defense_key": dk,
        "icon": defense_icon_static_path(dk),
        "amount": total_units,
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
        "cost_metal": int(row.get("cost_metal") or 0),
        "cost_crystal": int(row.get("cost_crystal") or 0),
    }


def defense_queue_for_client(
    player_id: int,
    planet_id: int,
    factory_level: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else _now())
    if defense_queue_table_ready(conn):
        finish_due_defense_jobs_for_planet(conn, int(planet_id), int(player_id), now=ts)

    rows = list_defense_queue_rows(planet_id, conn=conn) if defense_queue_table_ready(conn) else []
    jobs: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows):
        jobs.append(
            _defense_job_row_for_client(
                row,
                idx=idx,
                factory_level=factory_level,
                now=ts,
                conn=conn,
            )
        )

    first_remaining = jobs[0]["remaining"] if jobs else 0
    return {
        "queue": jobs,
        "summary": {
            "count": len(jobs),
            "limit": get_defense_queue_limit(conn=conn),
            "first_finish_in": first_remaining,
            "refund_percent": 60,
        },
    }


def build_defense_api_payload(player_id: int, planet_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        factory_level = get_defense_factory_level(player_id, planet_id, conn=conn)
        metal, crystal = _planet_resources(planet_id, conn=conn)
        stock = get_planet_defense(int(planet_id), conn=conn)
        buildable: List[Dict[str, Any]] = []
        queue_full = False
        if defense_queue_table_ready(conn):
            queue_full = queue_count(planet_id, conn=conn) >= get_defense_queue_limit(conn=conn)
        from .defense_defs import defense_icon_static_path

        for key in sorted(ACTIVE_DEFENSE_KEYS):
            if not defense_unlocked(
                key, factory_level, player_id=player_id, planet_id=planet_id, conn=conn
            ):
                continue
            cost = unit_build_cost(key)
            max_qty = max_build_amount_for_planet(
                metal,
                crystal,
                key,
                factory_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
            )
            can_build = not queue_full and max_qty > 0
            block_reason = ""
            if queue_full:
                block_reason = "queue_full"
            elif max_qty <= 0:
                block_reason = "not_enough_resources"
            buildable.append(
                {
                    "defense_key": key,
                    "name_key": str((get_defense(key) or {}).get("name_key") or f"defense_{key}"),
                    "description_key": str((get_defense(key) or {}).get("description_key") or f"defense_{key}_desc"),
                    "role": str((get_defense(key) or {}).get("role") or "turret"),
                    "icon": defense_icon_static_path(key),
                    "required_defense_factory_level": int(
                        (get_defense(key) or {}).get("required_defense_factory_level") or 99
                    ),
                    "cost_metal": cost["metal"],
                    "cost_crystal": cost["crystal"],
                    "build_seconds": unit_build_seconds(key, factory_level, conn=conn),
                    "max_build": max_qty,
                    "stock": int(stock.get(key, 0) or 0),
                    "can_build": can_build,
                    "block_reason": block_reason,
                }
            )
        queue = defense_queue_for_client(
            player_id, planet_id, factory_level, conn=conn
        )
        return {
            "defense_factory_level": factory_level,
            "buildable_defense": buildable,
            "current_defense": get_planet_defense(planet_id, conn=conn),
            "defense_queue": queue,
            "resources": {"metal": int(metal), "crystal": int(crystal)},
        }
    finally:
        if own and conn is not None:
            conn.close()


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
