"""Planet troop stock + Barracks training queue (Secret Vault Raid)."""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .db import db, table_columns, table_exists
from .shipyard import (
    BUILD_TIME_LEVEL_FACTOR,
    orbital_production_batch_capacity,
    production_job_duration_seconds,
    production_live_order_remaining_seconds,
    production_progressive_units_to_deliver,
    production_schedule_matches_live_params,
)
from .troop_defs import (
    ACTIVE_TROOP_KEYS,
    TROOP_ORDER,
    barracks_troop_capacity,
    get_troop,
    is_known_troop_key,
    normalize_troops,
)


def _now() -> float:
    return float(time.time())


def barracks_batch_capacity(barracks_level: int) -> int:
    """Parallel troops trained per cycle — same curve as orbital yard/defense."""
    lvl = max(1, int(barracks_level or 1))
    return orbital_production_batch_capacity(lvl)


def base_unit_seconds_for_troop(troop_key: str) -> int:
    spec = get_troop(troop_key) or {}
    return max(1, int(spec.get("train_seconds") or 1))


def unit_train_seconds(troop_key: str, barracks_level: int) -> int:
    """Cycle length for one batch at this barracks level (yard-style decay)."""
    base = base_unit_seconds_for_troop(troop_key)
    lvl = max(1, int(barracks_level or 1))
    seconds = max(1, int(math.ceil(base * (BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)))))
    return max(1, seconds)


def _job_duration_seconds(troop_key: str, amount: int, barracks_level: int) -> int:
    return production_job_duration_seconds(
        unit_seconds=unit_train_seconds(troop_key, barracks_level),
        amount=int(amount),
        batch_capacity=barracks_batch_capacity(barracks_level),
    )


def _job_scheduled_duration_seconds(row: Mapping[str, Any]) -> int:
    started = float(row.get("started_at") or 0)
    finish = float(row.get("finish_at") or 0)
    return max(1, int(finish - started))


def _job_total_units(row: Mapping[str, Any], barracks_level: int) -> int:
    from .shipyard import production_infer_total_units

    key = str(row["troop_key"])
    remaining = max(0, int(row.get("amount") or 0))
    return production_infer_total_units(
        remaining=remaining,
        scheduled_duration=_job_scheduled_duration_seconds(row),
        unit_seconds=unit_train_seconds(key, barracks_level),
        batch_capacity=barracks_batch_capacity(barracks_level),
    )


def _barracks_level_for_planet(planet_id: int, *, conn) -> int:
    from .models import get_planet_buildings

    bld = get_planet_buildings(int(planet_id), conn=conn) or {}
    return max(0, int(bld.get("barracks") or 0))


def progressive_troops_to_deliver(
    row: Mapping[str, Any],
    barracks_level: int,
    *,
    now: float,
) -> int:
    from .queue_poll import DUE_TIME_EPSILON_SEC

    remaining = max(0, int(row.get("amount") or 0))
    if remaining <= 0:
        return 0
    key = str(row["troop_key"])
    unit_sec = unit_train_seconds(key, barracks_level)
    cap = barracks_batch_capacity(barracks_level)
    total = _job_total_units(row, barracks_level)
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


def troops_schema_ready(conn) -> bool:
    return table_exists(conn, "planet_troops")


def troop_queue_table_ready(conn) -> bool:
    if not table_exists(conn, "troop_queue"):
        return False
    cols = table_columns(conn, "troop_queue")
    return "troop_key" in cols and "finish_at" in cols


def get_troop_queue_limit(*, conn=None) -> int:
    return 5


def get_planet_troops(planet_id: int, *, conn) -> Dict[str, int]:
    if not troops_schema_ready(conn):
        return {k: 0 for k in TROOP_ORDER}
    cur = conn.cursor()
    cur.execute(
        "SELECT troop_key, amount FROM planet_troops WHERE planet_id = ?;",
        (int(planet_id),),
    )
    stock = {k: 0 for k in TROOP_ORDER}
    for row in cur.fetchall() or []:
        key = str(row["troop_key"] or "")
        if key in stock:
            stock[key] = max(0, int(row["amount"] or 0))
    return stock


def planet_troop_total(planet_id: int, *, conn) -> int:
    return sum(get_planet_troops(planet_id, conn=conn).values())


def get_player_troop_counts(
    player_id: int,
    *,
    conn,
) -> Dict[str, int]:
    """All ground troops owned by a player across their planets."""
    if not troops_schema_ready(conn):
        return {}
    totals: Dict[str, int] = {}
    cur = conn.cursor()
    cur.execute(
        """
        SELECT pt.troop_key, SUM(pt.amount) AS amt
        FROM planet_troops pt
        INNER JOIN planets p ON p.id = pt.planet_id
        WHERE p.player_id = ? AND pt.amount > 0
        GROUP BY pt.troop_key;
        """,
        (int(player_id),),
    )
    for row in cur.fetchall():
        tk = str(row["troop_key"])
        if not is_known_troop_key(tk):
            continue
        totals[tk] = int(row["amt"] or 0)
    return totals


def add_planet_troops(planet_id: int, deltas: Mapping[str, int], *, conn) -> None:
    if not troops_schema_ready(conn):
        return
    cur = conn.cursor()
    for key, raw in (deltas or {}).items():
        if not is_known_troop_key(str(key)):
            continue
        try:
            delta = int(raw or 0)
        except (TypeError, ValueError):
            continue
        if delta == 0:
            continue
        cur.execute(
            """
            INSERT INTO planet_troops (planet_id, troop_key, amount)
            VALUES (?, ?, MAX(0, ?))
            ON CONFLICT(planet_id, troop_key) DO UPDATE SET
                amount = MAX(0, planet_troops.amount + ?);
            """,
            (int(planet_id), str(key), int(delta), int(delta)),
        )


def set_planet_troops(planet_id: int, stock: Mapping[str, int], *, conn) -> None:
    if not troops_schema_ready(conn):
        return
    cur = conn.cursor()
    for key in TROOP_ORDER:
        amount = max(0, int((stock or {}).get(key, 0) or 0))
        cur.execute(
            """
            INSERT INTO planet_troops (planet_id, troop_key, amount)
            VALUES (?, ?, ?)
            ON CONFLICT(planet_id, troop_key) DO UPDATE SET amount = excluded.amount;
            """,
            (int(planet_id), key, amount),
        )


def deduct_planet_troops(planet_id: int, need: Mapping[str, int], *, conn) -> bool:
    """Atomic deduct if stock sufficient. Returns False if short."""
    stock = get_planet_troops(planet_id, conn=conn)
    need_n = normalize_troops(need)
    for key, qty in need_n.items():
        if int(stock.get(key, 0) or 0) < qty:
            return False
    for key, qty in need_n.items():
        add_planet_troops(planet_id, {key: -qty}, conn=conn)
    return True


def list_troop_queue_rows(planet_id: int, *, conn) -> List[Dict[str, Any]]:
    if not troop_queue_table_ready(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM troop_queue
        WHERE planet_id = ? AND status = 'queued'
        ORDER BY queue_position ASC, id ASC;
        """,
        (int(planet_id),),
    )
    return [dict(r) for r in (cur.fetchall() or [])]


def queue_count(planet_id: int, *, conn) -> int:
    return len(list_troop_queue_rows(planet_id, conn=conn))


def sync_troop_queue_finish_times(planet_id: int, *, conn, now: Optional[float] = None) -> None:
    """Align finish_at with live batch remaining (same owner helpers as yard/defense)."""
    if not troop_queue_table_ready(conn):
        return
    bar_lvl = max(1, _barracks_level_for_planet(planet_id, conn=conn) or 1)
    ts = float(now if now is not None else _now())
    rows = list_troop_queue_rows(planet_id, conn=conn)
    if not rows:
        return

    cur = conn.cursor()
    head = rows[0]
    rem = max(0, int(head.get("amount") or 0))
    if rem > 0:
        key = str(head["troop_key"])
        unit = unit_train_seconds(key, bar_lvl)
        cap = barracks_batch_capacity(bar_lvl)
        scheduled = _job_scheduled_duration_seconds(head)
        total_guess = _job_total_units(head, bar_lvl)
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
                    "UPDATE troop_queue SET finish_at = ?, queue_position = 0 WHERE id = ?;",
                    (new_finish, int(head["id"])),
                )
            else:
                cur.execute(
                    """
                    UPDATE troop_queue
                    SET started_at = ?, finish_at = ?, queue_position = 0
                    WHERE id = ?;
                    """,
                    (started_at, new_finish, int(head["id"])),
                )
            head = {**head, "finish_at": new_finish, "started_at": started_at}
        schedule_at = float(head.get("finish_at") or (ts + live_rem))
    else:
        schedule_at = ts

    for idx, row in enumerate(rows[1:], start=1):
        key = str(row["troop_key"])
        amt = max(1, int(row.get("amount") or 1))
        duration = _job_duration_seconds(key, amt, bar_lvl)
        started = schedule_at
        finish = schedule_at + duration
        cur.execute(
            """
            UPDATE troop_queue
            SET queue_position = ?, started_at = ?, finish_at = ?
            WHERE id = ?;
            """,
            (idx, started, finish, int(row["id"])),
        )
        schedule_at = finish
    # Ensure head position is 0 even when rem==0 path skipped update above
    if rows:
        cur.execute(
            "UPDATE troop_queue SET queue_position = 0 WHERE id = ?;",
            (int(rows[0]["id"]),),
        )


def _finish_due_troop_jobs_impl(planet_id: int, *, conn, now: float) -> int:
    if not troop_queue_table_ready(conn) or not troops_schema_ready(conn):
        return 0
    finished = 0
    ts = float(now)
    bar_lvl = max(1, _barracks_level_for_planet(planet_id, conn=conn) or 1)
    cur = conn.cursor()

    while True:
        rows = list_troop_queue_rows(planet_id, conn=conn)
        if not rows:
            break
        head = rows[0]
        remaining_amt = max(0, int(head.get("amount") or 0))
        if remaining_amt <= 0:
            cur.execute("DELETE FROM troop_queue WHERE id = ?;", (int(head["id"]),))
            finished += 1
            sync_troop_queue_finish_times(planet_id, conn=conn, now=ts)
            continue

        to_deliver = progressive_troops_to_deliver(head, bar_lvl, now=ts)
        finish_at = float(head.get("finish_at") or 0)
        if to_deliver <= 0 and remaining_amt > 0 and finish_at > 0 and ts + 0.001 >= finish_at:
            to_deliver = remaining_amt
        if to_deliver <= 0:
            break

        key = str(head["troop_key"])
        add_planet_troops(int(planet_id), {key: to_deliver}, conn=conn)
        remaining = max(0, remaining_amt - to_deliver)
        if remaining <= 0:
            cur.execute("DELETE FROM troop_queue WHERE id = ?;", (int(head["id"]),))
            finished += 1
            sync_troop_queue_finish_times(planet_id, conn=conn, now=ts)
            continue

        cur.execute(
            "UPDATE troop_queue SET amount = ? WHERE id = ?;",
            (remaining, int(head["id"])),
        )
        sync_troop_queue_finish_times(planet_id, conn=conn, now=ts)
        break

    return finished


def finish_planet_troop_jobs(planet_id: int, *, conn, now: Optional[float] = None) -> int:
    return _finish_due_troop_jobs_impl(int(planet_id), conn=conn, now=float(now if now is not None else _now()))


def planet_ids_with_troop_queue(*, conn, player_id: Optional[int] = None) -> List[int]:
    if not troop_queue_table_ready(conn):
        return []
    cur = conn.cursor()
    if player_id is not None:
        cur.execute(
            """
            SELECT DISTINCT planet_id FROM troop_queue
            WHERE status = 'queued' AND player_id = ?;
            """,
            (int(player_id),),
        )
    else:
        cur.execute(
            "SELECT DISTINCT planet_id FROM troop_queue WHERE status = 'queued';"
        )
    return [int(r["planet_id"]) for r in (cur.fetchall() or [])]


def enqueue_troop_train(
    *,
    player_id: int,
    planet_id: int,
    troop_key: str,
    amount: int,
    barracks_level: int | None = None,
    conn,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    from .db import begin_write_transaction, commit, in_transaction, lock_planet_for_update, rollback
    from .models import get_planet_buildings, try_spend_resources_conn

    if not troop_queue_table_ready(conn) or not troops_schema_ready(conn):
        return False, "troops_unavailable", None
    key = str(troop_key or "").strip()
    spec = get_troop(key)
    if not spec:
        return False, "unknown_troop", None
    try:
        qty = max(1, int(amount or 0))
    except (TypeError, ValueError):
        return False, "invalid_amount", None

    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        # Finish-before-mutate (troops domain only — avoid nested global finish).
        finish_planet_troop_jobs(int(planet_id), conn=conn)
        lock_planet_for_update(conn, int(planet_id))
        bld = get_planet_buildings(int(planet_id), conn=conn) or {}
        bar_lvl = int(barracks_level) if barracks_level is not None else int(bld.get("barracks") or 0)
        req_lvl = int(spec.get("required_barracks_level") or 1)
        if bar_lvl < req_lvl:
            if began_tx:
                rollback(conn)
            return False, "barracks_level", None
        if queue_count(planet_id, conn=conn) >= get_troop_queue_limit(conn=conn):
            if began_tx:
                rollback(conn)
            return False, "queue_full", None

        current = planet_troop_total(planet_id, conn=conn)
        queued = sum(max(0, int(r.get("amount") or 0)) for r in list_troop_queue_rows(planet_id, conn=conn))
        stock_cap = barracks_troop_capacity(bar_lvl)
        if current + queued + qty > stock_cap:
            if began_tx:
                rollback(conn)
            return False, "capacity", None

        cost = spec.get("train_cost") or {}
        cost_m = int(cost.get("metal") or 0) * qty
        cost_c = int(cost.get("crystal") or 0) * qty

        if not try_spend_resources_conn(conn, int(planet_id), cost_m, cost_c):
            if began_tx:
                rollback(conn)
            return False, "insufficient_resources", None

        ts = _now()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT COALESCE(MAX(queue_position), -1) AS m FROM troop_queue
            WHERE planet_id = ? AND status = 'queued';
            """,
            (int(planet_id),),
        )
        pos = int((cur.fetchone() or {"m": -1})["m"]) + 1
        duration = _job_duration_seconds(key, qty, max(1, bar_lvl))
        cur.execute(
            """
            INSERT INTO troop_queue (
                player_id, planet_id, troop_key, amount, status,
                started_at, finish_at, created_at, queue_position,
                cost_metal, cost_crystal
            ) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?);
            """,
            (
                int(player_id),
                int(planet_id),
                key,
                qty,
                ts,
                ts + duration,
                ts,
                pos,
                cost_m,
                cost_c,
            ),
        )
        sync_troop_queue_finish_times(planet_id, conn=conn, now=ts)
        if began_tx:
            commit(conn)
        return True, "ok", {
            "troop_key": key,
            "amount": qty,
            "cost_metal": cost_m,
            "cost_crystal": cost_c,
            "train_seconds": unit_train_seconds(key, max(1, bar_lvl)),
            "batch_capacity": barracks_batch_capacity(max(1, bar_lvl)),
            "duration_seconds": duration,
        }
    except Exception:
        if began_tx:
            rollback(conn)
        raise


def cancel_troop_job(player_id: int, job_id: int, *, conn) -> Tuple[bool, str]:
    from .db import begin_write_transaction, commit, in_transaction, rollback

    if not troop_queue_table_ready(conn):
        return False, "troops_unavailable"
    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM troop_queue
            WHERE id = ? AND player_id = ? AND status = 'queued'
            LIMIT 1;
            """,
            (int(job_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            if began_tx:
                rollback(conn)
            return False, "not_found"
        planet_id = int(row["planet_id"])
        finish_planet_troop_jobs(int(planet_id), conn=conn)
        # Re-read after finish — job may have completed
        cur.execute(
            """
            SELECT * FROM troop_queue
            WHERE id = ? AND player_id = ? AND status = 'queued'
            LIMIT 1;
            """,
            (int(job_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            if began_tx:
                rollback(conn)
            return False, "not_found"
        # 50% refund if already started (first in queue), else 100%
        rows = list_troop_queue_rows(planet_id, conn=conn)
        is_head = bool(rows) and int(rows[0]["id"]) == int(job_id)
        refund_m = int(row["cost_metal"] or 0)
        refund_c = int(row["cost_crystal"] or 0)
        if is_head:
            refund_m = refund_m // 2
            refund_c = refund_c // 2
        if refund_m or refund_c:
            cur.execute(
                """
                UPDATE planets
                SET metal = metal + ?, crystal = crystal + ?
                WHERE id = ?;
                """,
                (int(refund_m), int(refund_c), int(planet_id)),
            )
        cur.execute("DELETE FROM troop_queue WHERE id = ?;", (int(job_id),))
        sync_troop_queue_finish_times(planet_id, conn=conn)
        if began_tx:
            commit(conn)
        return True, "ok"
    except Exception:
        if began_tx:
            rollback(conn)
        raise


def max_train_amount_for_planet(
    metal_have: float,
    crystal_have: float,
    troop_key: str,
    barracks_level: int,
    *,
    capacity_left: int,
) -> int:
    """Affordable train qty capped by planet resources and barracks stock capacity."""
    key = str(troop_key or "").strip()
    spec = get_troop(key)
    if not spec:
        return 0
    bar_lvl = max(0, int(barracks_level or 0))
    req = int(spec.get("required_barracks_level") or 1)
    if bar_lvl < req:
        return 0
    cost = spec.get("train_cost") or {}
    cost_m = int(cost.get("metal") or 0)
    cost_c = int(cost.get("crystal") or 0)
    limits: List[int] = [max(0, int(capacity_left))]
    if cost_m > 0:
        limits.append(int(metal_have) // cost_m)
    if cost_c > 0:
        limits.append(int(crystal_have) // cost_c)
    if not limits:
        return 0
    return max(0, min(limits))


def build_troops_state(planet_id: int, *, barracks_level: int, conn) -> Dict[str, Any]:
    import time as _time

    from .queue_card import map_card_jobs_to_mini_queue_jobs, map_troop_queue_to_card_jobs

    stock = get_planet_troops(planet_id, conn=conn)
    bar_lvl = max(0, int(barracks_level or 0))
    prod_lvl = max(1, bar_lvl) if bar_lvl > 0 else 1
    batch_cap = barracks_batch_capacity(prod_lvl) if bar_lvl > 0 else 0
    now = _time.time()
    queue = []
    for row in list_troop_queue_rows(planet_id, conn=conn):
        finish = int(float(row["finish_at"] or 0))
        started = int(float(row["started_at"] or 0))
        remaining = max(0, finish - int(now)) if finish > 0 else 0
        total_sec = max(1, finish - started) if finish > started else remaining or 1
        queue.append(
            {
                "id": int(row["id"]),
                "troop_key": str(row["troop_key"]),
                "amount": int(row["amount"] or 0),
                "started_at": started,
                "finish_at": finish,
                "queue_position": int(row["queue_position"] or 0),
                "remaining_seconds": remaining,
                "order_total_seconds": total_sec,
                "name_key": f"troop_{row['troop_key']}",
            }
        )
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    prow = cur.fetchone()
    try:
        metal_have = float((prow["metal"] if prow is not None else 0) or 0)
        crystal_have = float((prow["crystal"] if prow is not None else 0) or 0)
    except (TypeError, ValueError, KeyError, IndexError):
        metal_have = 0.0
        crystal_have = 0.0

    total = sum(stock.values())
    cap = barracks_troop_capacity(barracks_level)
    queued_amt = sum(max(0, int(j.get("amount") or 0)) for j in queue)
    capacity_left = max(0, int(cap) - int(total) - int(queued_amt))
    q_limit = get_troop_queue_limit(conn=conn)
    queue_full = len(queue) >= q_limit

    units = []
    for key in TROOP_ORDER:
        spec = get_troop(key) or {}
        cycle_sec = unit_train_seconds(key, prod_lvl) if bar_lvl > 0 else base_unit_seconds_for_troop(key)
        unlocked = bar_lvl >= int(spec.get("required_barracks_level") or 1)
        max_train = (
            max_train_amount_for_planet(
                metal_have,
                crystal_have,
                key,
                bar_lvl,
                capacity_left=capacity_left,
            )
            if unlocked and not queue_full
            else 0
        )
        train_cost = dict(spec.get("train_cost") or {})
        can_train = unlocked and max_train > 0 and not queue_full
        block_reason = ""
        if not unlocked:
            block_reason = "locked"
        elif queue_full:
            block_reason = "queue_full"
        elif max_train <= 0:
            block_reason = "not_enough_resources"
        units.append(
            {
                "key": key,
                "amount": int(stock.get(key, 0) or 0),
                "required_barracks_level": int(spec.get("required_barracks_level") or 1),
                "unlocked": unlocked,
                "train_cost": train_cost,
                "cost_metal": int(train_cost.get("metal") or 0),
                "cost_crystal": int(train_cost.get("crystal") or 0),
                "train_seconds": cycle_sec,
                "base_train_seconds": base_unit_seconds_for_troop(key),
                "batch_capacity": batch_cap,
                "max_train": int(max_train),
                "can_train": bool(can_train),
                "block_reason": block_reason,
                "name_key": spec.get("name_key"),
                "description_key": spec.get("description_key"),
                "icon": spec.get("icon") or f"img/troops/{key}.png",
                "attack": int(spec.get("attack") or 0),
                "defense": int(spec.get("defense") or 0),
                "hull": int(spec.get("hull") or 0),
            }
        )
    state: Dict[str, Any] = {
        "stock": stock,
        "units": units,
        "queue": queue,
        "total": total,
        "capacity": cap,
        "capacity_left": capacity_left,
        "barracks_level": bar_lvl,
        "batch_capacity": batch_cap,
        "queue_limit": q_limit,
        "queue_count": len(queue),
        "summary": {"count": len(queue), "limit": q_limit},
    }
    card_jobs = map_troop_queue_to_card_jobs(state, now=now)
    state["mini_queue_jobs"] = map_card_jobs_to_mini_queue_jobs(
        card_jobs, domain="troops", now=now
    )
    return state

