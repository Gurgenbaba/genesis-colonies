"""GC-MANDO-RELAY-002 — cooldown-gated shipless logistics inside one empire.

The relay is intentionally separate from Fleet:
- own planets only,
- no ships, fleet slots or fleet_movements,
- collect cooldown belongs to each successful source planet,
- distribute cooldown belongs to each successful target planet,
- resource debit/credit + cooldown writes commit in one short transaction.

Normal transport, deploy, attack, expedition and inter-player movement remain Fleet-owned.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

from flask import jsonify, request, session

from .auth import require_login_api
from .db import begin_write_transaction, commit, db, lock_planet_for_update, rollback
from .models import get_idempotent_action, resource_numeric_cast_param, save_idempotent_action
from .resources import LOOT_RESOURCE_KEYS, normalize_resource_stock, update_planet_resources

logger = logging.getLogger(__name__)

RELAY_COOLDOWN_SECONDS = 30 * 60
MAX_RELAY_PLANETS = 64
_RELAY_DIRECTIONS = frozenset({"collect", "distribute"})


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
        if len(out) >= MAX_RELAY_PLANETS:
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


def _validate_owned_participants(
    *,
    player_id: int,
    anchor_planet_id: int,
    other_planet_ids: Sequence[int],
    conn,
) -> tuple[bool, str, Dict[int, Dict[str, Any]], list[int]]:
    participant_ids = sorted({int(anchor_planet_id), *(int(x) for x in other_planet_ids)})
    owned = _owned_planets(int(player_id), participant_ids, conn=conn)
    if int(anchor_planet_id) not in owned:
        return False, "invalid_target", owned, participant_ids
    missing = [pid for pid in participant_ids if pid not in owned]
    if missing:
        return False, "foreign_planet", owned, missing
    return True, "", owned, participant_ids


def _lock_planets(participant_ids: Sequence[int], *, conn) -> None:
    for planet_id in sorted({int(x) for x in participant_ids}):
        lock_planet_for_update(conn, planet_id)


def _cooldown_rows(player_id: int, planet_ids: Sequence[int], direction: str, *, conn) -> Dict[int, int]:
    ids = sorted({int(pid) for pid in planet_ids if int(pid) > 0})
    if not ids:
        return {}
    direction_n = str(direction or "").strip().lower()
    if direction_n not in _RELAY_DIRECTIONS:
        raise ValueError("invalid relay direction")
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT planet_id, ready_at
        FROM empire_resource_relay_cooldowns
        WHERE player_id = ?
          AND direction = ?
          AND planet_id IN ({placeholders});
        """,
        (int(player_id), direction_n, *ids),
    ).fetchall()
    return {int(row["planet_id"]): max(0, int(row["ready_at"] or 0)) for row in rows}


def _cooldown_partition(
    player_id: int,
    planet_ids: Sequence[int],
    direction: str,
    *,
    now: int,
    conn,
) -> tuple[list[int], list[Dict[str, Any]]]:
    rows = _cooldown_rows(player_id, planet_ids, direction, conn=conn)
    ready: list[int] = []
    skipped: list[Dict[str, Any]] = []
    for planet_id in planet_ids:
        pid = int(planet_id)
        ready_at = int(rows.get(pid, 0))
        if ready_at > int(now):
            skipped.append(
                {
                    "planet_id": pid,
                    "reason": "relay_cooldown",
                    "ready_at": ready_at,
                    "retry_after_sec": max(1, ready_at - int(now)),
                }
            )
        else:
            ready.append(pid)
    return ready, skipped


def _set_cooldown(
    player_id: int,
    planet_id: int,
    direction: str,
    *,
    now: int,
    conn,
) -> int:
    direction_n = str(direction or "").strip().lower()
    if direction_n not in _RELAY_DIRECTIONS:
        raise ValueError("invalid relay direction")
    ready_at = int(now) + RELAY_COOLDOWN_SECONDS
    conn.execute(
        """
        INSERT INTO empire_resource_relay_cooldowns
            (player_id, planet_id, direction, ready_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(player_id, planet_id, direction) DO UPDATE SET
            ready_at = excluded.ready_at,
            updated_at = excluded.updated_at;
        """,
        (int(player_id), int(planet_id), direction_n, ready_at, int(now)),
    )
    return ready_at


def _sync_planets(player_id: int, planet_ids: Sequence[int], *, conn) -> Dict[int, Dict[str, Any]]:
    synced: Dict[int, Dict[str, Any]] = {}
    for planet_id in sorted({int(x) for x in planet_ids}):
        row = conn.execute(
            "SELECT * FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (planet_id, int(player_id)),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"owned relay planet disappeared: {planet_id}")
        planet, *_ = update_planet_resources(
            dict(row),
            conn=conn,
            skip_queue_finish=True,
            persist=True,
        )
        synced[planet_id] = dict(planet)
    return synced


def _cooldown_state(player_id: int, *, conn, now: int | None = None) -> Dict[str, Any]:
    ts = int(time.time()) if now is None else int(now)
    rows = conn.execute(
        """
        SELECT planet_id, direction, ready_at
        FROM empire_resource_relay_cooldowns
        WHERE player_id = ?
        ORDER BY planet_id ASC, direction ASC;
        """,
        (int(player_id),),
    ).fetchall()
    collect: Dict[str, int] = {}
    distribute: Dict[str, int] = {}
    for row in rows:
        direction = str(row["direction"] or "")
        planet_id = str(int(row["planet_id"]))
        ready_at = max(0, int(row["ready_at"] or 0))
        if direction == "collect":
            collect[planet_id] = ready_at
        elif direction == "distribute":
            distribute[planet_id] = ready_at
    return {
        "cooldown_seconds": RELAY_COOLDOWN_SECONDS,
        "server_now": ts,
        "collect": collect,
        "distribute": distribute,
    }


def _colony_resource_payload(player_id: int, planet_ids: Sequence[int], *, conn) -> Dict[str, Dict[str, int]]:
    rows = _owned_planets(player_id, planet_ids, conn=conn)
    return {str(pid): normalize_resource_stock(row) for pid, row in rows.items()}


def collect_empire_resources(
    *,
    player_id: int,
    target_planet_id: int,
    source_planet_ids: Sequence[int],
    conn,
    now: int | None = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Harvest all stock from every ready selected source into one owned hub."""
    uid = int(player_id)
    target_id = int(target_planet_id or 0)
    sources = _normalize_planet_ids(source_planet_ids, exclude=target_id)
    ts = int(time.time()) if now is None else int(now)

    if uid <= 0 or target_id <= 0:
        return False, "invalid_target", {}
    if not sources:
        return False, "no_planets", {}

    from .options import vacation_freezes_account_progress

    if vacation_freezes_account_progress(uid, conn=conn):
        return False, "vacation_mode", {}

    valid, reason, _owned, detail = _validate_owned_participants(
        player_id=uid,
        anchor_planet_id=target_id,
        other_planet_ids=sources,
        conn=conn,
    )
    if not valid:
        return False, reason, {"planet_ids": detail if reason == "foreign_planet" else []}

    participant_ids = sorted({target_id, *sources})
    _lock_planets(participant_ids, conn=conn)

    ready_sources, skipped = _cooldown_partition(
        uid, sources, "collect", now=ts, conn=conn
    )
    if not ready_sources:
        retry = min((int(x["retry_after_sec"]) for x in skipped), default=RELAY_COOLDOWN_SECONDS)
        return False, "relay_cooldown", {
            "target_planet_id": target_id,
            "source_planet_ids": sources,
            "processed_planet_ids": [],
            "skipped": skipped,
            "retry_after_sec": retry,
            "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        }

    synced = _sync_planets(uid, [target_id, *ready_sources], conn=conn)
    moved = {key: 0 for key in LOOT_RESOURCE_KEYS}
    moved_by_source: Dict[str, Dict[str, int]] = {}
    processed: list[int] = []

    for source_id in ready_sources:
        stock = normalize_resource_stock(synced[source_id])
        if sum(stock.values()) <= 0:
            skipped.append(
                {
                    "planet_id": source_id,
                    "reason": "no_resources",
                    "ready_at": 0,
                    "retry_after_sec": 0,
                }
            )
            continue
        processed.append(source_id)
        moved_by_source[str(source_id)] = stock
        for key in LOOT_RESOURCE_KEYS:
            moved[key] += int(stock[key])

    if not processed:
        return False, "no_resources", {
            "target_planet_id": target_id,
            "source_planet_ids": sources,
            "processed_planet_ids": [],
            "skipped": skipped,
            "moved": moved,
            "moved_total": 0,
            "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        }

    for source_id in processed:
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
        ready_at = _set_cooldown(uid, source_id, "collect", now=ts, conn=conn)
        for item in skipped:
            if int(item.get("planet_id") or 0) == source_id:
                item["ready_at"] = ready_at

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

    colony_resources = _colony_resource_payload(
        uid, [target_id, *ready_sources], conn=conn
    )
    return True, "empire_relay_collect_ok", {
        "target_planet_id": target_id,
        "source_planet_ids": sources,
        "processed_planet_ids": processed,
        "processed_count": len(processed),
        "skipped": skipped,
        "moved": moved,
        "moved_total": sum(int(v) for v in moved.values()),
        "moved_by_source": moved_by_source,
        "hub_resources": colony_resources.get(str(target_id), normalize_resource_stock({})),
        "colony_resources": colony_resources,
        "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        "uses_ships": False,
        "uses_fleet_slots": False,
    }


def _normalize_requested_resources(resources: Mapping[str, Any] | None) -> Dict[str, int]:
    return normalize_resource_stock(resources or {})


def _equal_allocations(resources: Mapping[str, int], target_planet_ids: Sequence[int]) -> Dict[int, Dict[str, int]]:
    targets = sorted({int(x) for x in target_planet_ids})
    if not targets:
        return {}
    result = {pid: {key: 0 for key in LOOT_RESOURCE_KEYS} for pid in targets}
    count = len(targets)
    for key in LOOT_RESOURCE_KEYS:
        total = max(0, int(resources.get(key) or 0))
        base, remainder = divmod(total, count)
        for idx, planet_id in enumerate(targets):
            result[planet_id][key] = base + (1 if idx < remainder else 0)
    return result


def distribute_empire_resources(
    *,
    player_id: int,
    origin_planet_id: int,
    target_planet_ids: Sequence[int],
    resources: Mapping[str, Any] | None,
    conn,
    now: int | None = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Split a requested total across selected owned targets; deliver ready targets only."""
    uid = int(player_id)
    origin_id = int(origin_planet_id or 0)
    targets = _normalize_planet_ids(target_planet_ids, exclude=origin_id)
    requested = _normalize_requested_resources(resources)
    ts = int(time.time()) if now is None else int(now)

    if uid <= 0 or origin_id <= 0:
        return False, "invalid_target", {}
    if not targets:
        return False, "no_planets", {}
    if sum(requested.values()) <= 0:
        return False, "no_resources", {"requested": requested}

    from .options import vacation_freezes_account_progress

    if vacation_freezes_account_progress(uid, conn=conn):
        return False, "vacation_mode", {}

    valid, reason, _owned, detail = _validate_owned_participants(
        player_id=uid,
        anchor_planet_id=origin_id,
        other_planet_ids=targets,
        conn=conn,
    )
    if not valid:
        return False, reason, {"planet_ids": detail if reason == "foreign_planet" else []}

    participant_ids = sorted({origin_id, *targets})
    _lock_planets(participant_ids, conn=conn)

    ready_targets, skipped = _cooldown_partition(
        uid, targets, "distribute", now=ts, conn=conn
    )
    if not ready_targets:
        retry = min((int(x["retry_after_sec"]) for x in skipped), default=RELAY_COOLDOWN_SECONDS)
        return False, "relay_cooldown", {
            "origin_planet_id": origin_id,
            "target_planet_ids": targets,
            "processed_planet_ids": [],
            "skipped": skipped,
            "retry_after_sec": retry,
            "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        }

    synced = _sync_planets(uid, [origin_id, *ready_targets], conn=conn)
    allocations = _equal_allocations(requested, targets)
    deliver: Dict[int, Dict[str, int]] = {}
    debit = {key: 0 for key in LOOT_RESOURCE_KEYS}

    for target_id in ready_targets:
        allocation = allocations.get(target_id) or {key: 0 for key in LOOT_RESOURCE_KEYS}
        if sum(allocation.values()) <= 0:
            skipped.append(
                {
                    "planet_id": target_id,
                    "reason": "no_resources",
                    "ready_at": 0,
                    "retry_after_sec": 0,
                }
            )
            continue
        deliver[target_id] = allocation
        for key in LOOT_RESOURCE_KEYS:
            debit[key] += int(allocation[key])

    if not deliver:
        return False, "no_resources", {
            "origin_planet_id": origin_id,
            "target_planet_ids": targets,
            "requested": requested,
            "skipped": skipped,
            "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        }

    available = normalize_resource_stock(synced[origin_id])
    if any(int(debit[key]) > int(available[key]) for key in LOOT_RESOURCE_KEYS):
        return False, "not_enough_resources", {
            "origin_planet_id": origin_id,
            "target_planet_ids": targets,
            "requested": requested,
            "required": debit,
            "available": available,
            "skipped": skipped,
            "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        }

    conn.execute(
        """
        UPDATE planets
        SET metal = metal - CAST(? AS NUMERIC),
            crystal = crystal - CAST(? AS NUMERIC),
            fuel_cells = fuel_cells - CAST(? AS NUMERIC)
        WHERE id = ? AND player_id = ?;
        """,
        (
            resource_numeric_cast_param(debit["metal"]),
            resource_numeric_cast_param(debit["crystal"]),
            resource_numeric_cast_param(debit["fuel_cells"]),
            origin_id,
            uid,
        ),
    )

    processed: list[int] = []
    ready_at_by_target: Dict[str, int] = {}
    for target_id in sorted(deliver):
        allocation = deliver[target_id]
        conn.execute(
            """
            UPDATE planets
            SET metal = metal + CAST(? AS NUMERIC),
                crystal = crystal + CAST(? AS NUMERIC),
                fuel_cells = fuel_cells + CAST(? AS NUMERIC)
            WHERE id = ? AND player_id = ?;
            """,
            (
                resource_numeric_cast_param(allocation["metal"]),
                resource_numeric_cast_param(allocation["crystal"]),
                resource_numeric_cast_param(allocation["fuel_cells"]),
                target_id,
                uid,
            ),
        )
        processed.append(target_id)
        ready_at_by_target[str(target_id)] = _set_cooldown(
            uid, target_id, "distribute", now=ts, conn=conn
        )

    colony_resources = _colony_resource_payload(
        uid, [origin_id, *ready_targets], conn=conn
    )
    return True, "empire_relay_distribute_ok", {
        "origin_planet_id": origin_id,
        "target_planet_ids": targets,
        "processed_planet_ids": processed,
        "processed_count": len(processed),
        "skipped": skipped,
        "requested": requested,
        "debited": debit,
        "delivered_by_target": {str(pid): deliver[pid] for pid in sorted(deliver)},
        "ready_at_by_target": ready_at_by_target,
        "hub_resources": colony_resources.get(str(origin_id), normalize_resource_stock({})),
        "colony_resources": colony_resources,
        "cooldowns": _cooldown_state(uid, conn=conn, now=ts),
        "uses_ships": False,
        "uses_fleet_slots": False,
    }


def _request_id(data: Mapping[str, Any]) -> str:
    return str(data.get("request_id") or "").strip()[:128]


def _status_for_reason(reason: str) -> int:
    return 429 if str(reason) == "relay_cooldown" else 400


def _action_body(ok: bool, reason: str, payload: Mapping[str, Any], *, success_key: str) -> Dict[str, Any]:
    return {
        "ok": bool(ok),
        "error": "" if ok else str(reason),
        "reason": str(reason),
        "message_key": success_key if ok else f"fleet_error_{reason}",
        "data": dict(payload or {}),
        "server_now": int(time.time()),
    }


def register_empire_relay_routes(app) -> None:
    if "api_empire_relay_state" not in app.view_functions:
        @app.get("/api/logistics/relay/state", endpoint="api_empire_relay_state")
        @require_login_api
        def _api_empire_relay_state():
            uid = int(session.get("user_id") or 0)
            conn = db()
            try:
                return jsonify({"ok": True, "data": _cooldown_state(uid, conn=conn)})
            finally:
                conn.close()

    if "api_empire_relay_collect" not in app.view_functions:
        @app.post("/api/logistics/relay/collect", endpoint="api_empire_relay_collect")
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
                logger.exception("empire collect relay failed player=%s target=%s", uid, target_id)
                return jsonify(_action_body(False, "server_error", {}, success_key="logistics_relay_collect_success")), 500
            finally:
                conn.close()

            body = _action_body(ok, reason, payload, success_key="logistics_relay_collect_success")
            if ok and request_id:
                save_idempotent_action(uid, request_id, body)
            return jsonify(body), (200 if ok else _status_for_reason(reason))

    if "api_empire_relay_distribute" not in app.view_functions:
        @app.post("/api/logistics/relay/distribute", endpoint="api_empire_relay_distribute")
        @require_login_api
        def _api_empire_relay_distribute():
            uid = int(session.get("user_id") or 0)
            data = request.get_json(silent=True) or {}
            request_id = _request_id(data)
            if request_id:
                cached = get_idempotent_action(uid, request_id)
                if cached is not None:
                    return jsonify(cached)

            try:
                origin_id = int(data.get("origin_planet_id") or 0)
            except (TypeError, ValueError):
                origin_id = 0
            targets = data.get("target_planet_ids") or []
            if not isinstance(targets, (list, tuple)):
                targets = []

            conn = db()
            try:
                begin_write_transaction(conn)
                ok, reason, payload = distribute_empire_resources(
                    player_id=uid,
                    origin_planet_id=origin_id,
                    target_planet_ids=targets,
                    resources=data.get("resources") if isinstance(data.get("resources"), Mapping) else {},
                    conn=conn,
                )
                if ok:
                    commit(conn)
                else:
                    rollback(conn)
            except Exception:
                rollback(conn)
                logger.exception("empire distribute relay failed player=%s origin=%s", uid, origin_id)
                return jsonify(_action_body(False, "server_error", {}, success_key="logistics_relay_distribute_success")), 500
            finally:
                conn.close()

            body = _action_body(ok, reason, payload, success_key="logistics_relay_distribute_success")
            if ok and request_id:
                save_idempotent_action(uid, request_id, body)
            return jsonify(body), (200 if ok else _status_for_reason(reason))
