"""Canonical JSON envelope for defense HTTP APIs (GC-413)."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

CANCEL_REFUND_RATIO = 0.6


def defense_ok(
    *,
    state: Any = None,
    queue: Any = None,
    defenses: Any = None,
    reason: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": True}
    if reason:
        out["reason"] = reason
    if state is not None:
        out["state"] = state
    if queue is not None:
        out["queue"] = queue
    if defenses is not None:
        out["defenses"] = defenses
    out.update(extra)
    return out


def defense_err(
    error: str,
    *,
    state: Any = None,
    queue: Any = None,
    defenses: Any = None,
    reason: str = "",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "error": error,
        "reason": reason or error,
    }
    if state is not None:
        out["state"] = state
    if queue is not None:
        out["queue"] = queue
    if defenses is not None:
        out["defenses"] = defenses
    return out


def defense_schema_available(conn) -> bool:
    from game.defense import defense_queue_table_ready
    from game.models import defense_schema_ready

    return defense_schema_ready(conn) and defense_queue_table_ready(conn)


def resolve_context_planet_id(
    user_id: int,
    planet_id_raw: int | None,
    *,
    conn,
) -> Tuple[int | None, str | None]:
    from game.shipyard import resolve_owned_planet_id

    return resolve_owned_planet_id(user_id, planet_id_raw, conn=conn)


def build_queue_slice(player_id: int, planet_id: int, *, conn) -> Dict[str, Any]:
    from game.defense import defense_queue_for_client, get_defense_factory_level

    factory_level = get_defense_factory_level(int(player_id), int(planet_id), conn=conn)
    return defense_queue_for_client(
        int(player_id),
        int(planet_id),
        factory_level,
        conn=conn,
    )


def build_defenses_slice(player_id: int, planet_id: int, *, conn) -> Dict[str, Any]:
    from game.defense import build_defense_api_payload

    payload = build_defense_api_payload(int(player_id), int(planet_id), conn=conn)
    queue_key = payload.pop("defense_queue", {"queue": [], "summary": {}})
    _ = queue_key
    return {"ready": True, **payload}


def build_overview_slice(player_id: int, planet_id: int, *, conn) -> Dict[str, Any]:
    from game.defense import get_defense_factory_level
    from game.defense_page import _planet_meta
    from game.models import get_planet_defense

    stock = get_planet_defense(int(planet_id), conn=conn)
    queue = build_queue_slice(int(player_id), int(planet_id), conn=conn)
    return {
        **_planet_meta(int(planet_id), conn=conn),
        "defense_factory_level": get_defense_factory_level(int(player_id), int(planet_id), conn=conn),
        "current_defense": stock,
        "total_units": sum(int(v or 0) for v in stock.values()),
        "queue_summary": queue.get("summary") or {},
    }


def fetch_defense_slices(
    player_id: int,
    planet_id: int,
    *,
    conn,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    return (
        build_queue_slice(int(player_id), int(planet_id), conn=conn),
        build_defenses_slice(int(player_id), int(planet_id), conn=conn),
    )


def _refund_planet_resources(
    conn,
    planet_id: int,
    *,
    metal: int,
    crystal: int,
) -> None:
    if metal <= 0 and crystal <= 0:
        return
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal = metal + ?,
            crystal = crystal + ?
        WHERE id = ?;
        """,
        (int(metal), int(crystal), int(planet_id)),
    )


def _renumber_defense_queue(conn, planet_id: int) -> None:
    from game.defense import list_defense_queue_rows

    rows = list_defense_queue_rows(int(planet_id), conn=conn)
    cur = conn.cursor()
    for idx, row in enumerate(rows):
        cur.execute(
            "UPDATE defense_queue SET queue_position = ? WHERE id = ?;",
            (idx, int(row["id"])),
        )


def cancel_defense_job(
    *,
    player_id: int,
    planet_id: int,
    job_id: int,
    conn,
) -> Tuple[bool, str]:
    from game.db import begin_write_transaction, commit, in_transaction, rollback
    from game.defense import (
        QUEUE_STATUS_QUEUED,
        get_defense_factory_level,
        lock_planet_for_update,
        recalculate_queue_finish_times,
    )

    began_tx = False
    try:
        if not in_transaction(conn):
            begin_write_transaction(conn)
            began_tx = True
        lock_planet_for_update(conn, int(planet_id))

        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM defense_queue
            WHERE id = ? AND planet_id = ? AND player_id = ? AND status = ?
            LIMIT 1;
            """,
            (int(job_id), int(planet_id), int(player_id), QUEUE_STATUS_QUEUED),
        )
        row = cur.fetchone()
        if not row:
            if began_tx:
                rollback(conn)
            return False, "queue_job_not_found"

        job = dict(row)
        refund_m = int(int(job.get("cost_metal") or 0) * CANCEL_REFUND_RATIO)
        refund_c = int(int(job.get("cost_crystal") or 0) * CANCEL_REFUND_RATIO)

        cur.execute("DELETE FROM defense_queue WHERE id = ?;", (int(job_id),))
        _refund_planet_resources(conn, int(planet_id), metal=refund_m, crystal=refund_c)
        _renumber_defense_queue(conn, int(planet_id))
        factory_level = get_defense_factory_level(int(player_id), int(planet_id), conn=conn)
        recalculate_queue_finish_times(int(planet_id), factory_level, conn=conn)

        if began_tx:
            commit(conn)
        return True, ""
    except Exception:
        if began_tx:
            rollback(conn)
        raise


def empty_defense_slices(*, ready: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    queue: Dict[str, Any] = {"queue": [], "summary": {"count": 0, "limit": 0, "first_finish_in": 0}}
    defenses: Dict[str, Any] = {
        "ready": ready,
        "defense_factory_level": 0,
        "buildable_defense": [],
        "current_defense": {},
        "resources": {"metal": 0, "crystal": 0},
    }
    return queue, defenses
