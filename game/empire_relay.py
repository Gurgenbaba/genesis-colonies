"""GC-MANDO-RELAY-001 — shipless resource consolidation inside one empire.

This is deliberately not a Fleet movement. It only moves already-owned resources
between planets belonging to the same player, inside one short DB transaction.
PvP transport, attacks, expeditions and inter-player logistics remain Fleet-owned.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from flask import jsonify, request, session

from .auth import require_login_api
from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback
from .models import (
    get_idempotent_action,
    resource_numeric_cast_param,
    save_idempotent_action,
)
from .resources import LOOT_RESOURCE_KEYS, normalize_resource_stock, update_planet_resources

logger = logging.getLogger(__name__)

MAX_RELAY_SOURCES = 32


def _normalize_planet_ids(values: Iterable[Any], *, exclude: int = 0) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for raw in values or ():
        try:
            planet_id = int(raw)
        except (TypeError, ValueError):
            continue
        if planet_id <= 0 or planet_id == int(exclude) or planet_id in seen:
            continue
        seen.add(planet_id)
        out.append(planet_id)
        if len(out) >= MAX_RELAY_SOURCES:
            break
    return out


def _owned_planets(player_id: int, planet_ids: Sequence[int], *, conn) -> Dict[int, Dict[str, Any]]:
    ids = sorted({int(pid) for pid in planet_ids if int(pid) > 0})
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT *
        FROM planets
        WHERE player_id = ?
          AND id IN ({placeholders})
        ORDER BY id ASC;
        """,
        (int(player_id), *ids),
    ).fetchall()
    return {int(row["id"]): dict(row) for row in rows}


def collect_empire_resources(
    *,
    player_id: int,
    target_planet_id: int,
    source_planet_ids: Sequence[int],
    conn,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Move all resource stock from selected owned colonies to one owned hub.

    Caller owns the write transaction. PostgreSQL rows are locked in ascending
    planet-id order before any resource tick or transfer so simultaneous relay,
    queue and Fleet writers cannot double-spend or deadlock on opposite orders.
    """
    uid = int(player_id)
    target_id = int(target_planet_id or 0)
    if uid <= 0 or target_id <= 0:
        return False, "invalid_target", {}

    sources = _normalize_planet_ids(source_planet_ids, exclude=target_id)
    if not sources:
        return False, "no_planets", {}

    from .options import vacation_freezes_account_progress

    if vacation_freezes_account_progress(uid, conn=conn):
        return False, "vacation_mode", {}

    participant_ids = sorted({target_id, *sources})
    owned = _owned_planets(uid, participant_ids, conn=conn)
    if target_id not in owned:
        return False, "invalid_target", {}
    missing_sources = [pid for pid in sources if pid not in owned]
    if missing_sources:
        return False, "foreign_planet", {"planet_ids": missing_sources}

    for planet_id in participant_ids:
        lock_planet_for_update(conn, planet_id)

    # Capture canonical production/evolution state immediately before moving stock.
    synced: Dict[int, Dict[str, Any]] = {}
    for planet_id in participant_ids:
        row = conn.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (planet_id, uid),
        ).fetchone()
        if row is None:
            return False, "planet_not_found", {"planet_id": planet_id}
        planet, *_ = update_planet_resources(
            dict(row),
            conn=conn,
            skip_queue_finish=True,
            persist=True,
        )
        synced[planet_id] = dict(planet)

    moved = {key: 0 for key in LOOT_RESOURCE_KEYS}
    moved_by_source: Dict[str, Dict[str, int]] = {}
    for source_id in sources:
        stock = normalize_resource_stock(synced[source_id])
        moved_by_source[str(source_id)] = stock
        for key in LOOT_RESOURCE_KEYS:
            moved[key] += int(stock[key])

    moved_total = sum(int(v) for v in moved.values())
    if moved_total <= 0:
        return False, "no_resources", {
            "target_planet_id": target_id,
            "source_planet_ids": sources,
            "moved": moved,
            "moved_total": 0,
        }

    # Sources are drained only after every participant has been validated + locked.
    for source_id in sources:
        conn.execute(
            """
            UPDATE planets
            SET metal = CAST(0 AS NUMERIC),
                crystal = CAST(0 AS NUMERIC),
                fuel_cells = CAST(0 AS NUMERIC)
            WHERE id = ? AND player_id = ?;
            """,
            (source_id, uid),
        )

    conn.execute(
        """
        UPDATE planets
        SET metal = metal + CAST(? AS NUMERIC),
            crystal = crystal + CAST(? AS NUMERIC),
            fuel_cells = fuel_cells + CAST(? AS NUMERIC)
        WHERE id = ? AND player_id = ?;
        """,
        (
            resource_numeric_cast_param(moved["metal"]),
            resource_numeric_cast_param(moved["crystal"]),
            resource_numeric_cast_param(moved["fuel_cells"]),
            target_id,
            uid,
        ),
    )

    rows = _owned_planets(uid, participant_ids, conn=conn)
    colony_resources = {
        str(pid): normalize_resource_stock(row)
        for pid, row in rows.items()
    }
    hub_resources = colony_resources.get(str(target_id), normalize_resource_stock({}))

    return True, "empire_relay_collect_ok", {
        "target_planet_id": target_id,
        "source_planet_ids": sources,
        "source_count": len(sources),
        "moved": moved,
        "moved_total": moved_total,
        "moved_by_source": moved_by_source,
        "hub_resources": hub_resources,
        "colony_resources": colony_resources,
        "uses_ships": False,
        "uses_fleet_slots": False,
    }


def _request_id(data: Mapping[str, Any]) -> str:
    value = str(data.get("request_id") or "").strip()
    return value[:128]


def register_empire_relay_routes(app) -> None:
    endpoint = "api_empire_relay_collect"
    if endpoint in app.view_functions:
        return

    @app.post("/api/logistics/relay/collect", endpoint=endpoint)
    @require_login_api
    def _api_empire_relay_collect():
        uid = int(session.get("user_id") or 0)
        data = request.get_json(silent=True) or {}
        request_id = _request_id(data)
        if request_id:
            cached = get_idempotent_action(uid, request_id)
            if cached is not None:
                return jsonify(cached)

        try:
            target_id = int(data.get("target_planet_id") or 0)
        except (TypeError, ValueError):
            target_id = 0
        sources = data.get("source_planet_ids") or []
        if not isinstance(sources, (list, tuple)):
            sources = []

        conn = db()
        try:
            begin_write_transaction(conn)
            ok, reason, payload = collect_empire_resources(
                player_id=uid,
                target_planet_id=target_id,
                source_planet_ids=sources,
                conn=conn,
            )
            if ok:
                commit(conn)
            else:
                rollback(conn)
        except Exception:
            rollback(conn)
            logger.exception("empire resource relay failed player=%s target=%s", uid, target_id)
            return jsonify({
                "ok": False,
                "error": "server_error",
                "reason": "server_error",
                "message_key": "fleet_error_generic",
                "data": {},
                "server_now": int(time.time()),
            }), 500
        finally:
            conn.close()

        body = {
            "ok": bool(ok),
            "error": "" if ok else reason,
            "reason": reason,
            "message_key": "fleet_logistics_collect_ok" if ok else f"fleet_error_{reason}",
            "data": payload,
            "server_now": int(time.time()),
        }
        if request_id:
            save_idempotent_action(uid, request_id, body)
        return jsonify(body), (200 if ok else 400)
