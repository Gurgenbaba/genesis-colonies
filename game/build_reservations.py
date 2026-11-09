"""GC-RESERVE-001 - reserve the next building ("reserve next purchase", phase 1: buildings only).

A reservation is the player's INTENT: "start this building as soon as I can pay for it". It holds no
resources, grants none, shortens no timer and never starts earlier than the moment it is evaluated.
When funds exist and a queue slot is free, the server starts it through the one canonical owner,
``game.buildings.queue_build_for_planet`` - same cost (priced at that moment), prerequisites, level
caps, Ascension rebuild share, queue limit and timers as a manual click. This module adds nothing to
the economy; it only remembers the intent and calls the owner at the right time.

Why the charge cannot happen twice (see ``docs/GC_RESERVE_NEXT_PURCHASE.md`` section 7):

* the debit, the job insert and the claim ``armed -> started`` are ONE transaction inside the owner
  (``reservation=`` hook); a lost claim (``claim_reservation_in_transaction`` -> False) rolls the
  debit and the job back,
* the claim is a compare-and-swap on ``state = 'armed'``; a replay or a second worker finds nothing to do,
* the database refuses a second armed row per planet and a second reservation per job (migration 189).

Feature flag: ``GC_RESERVE_NEXT_PURCHASE`` = ``off`` (default) | ``test`` | ``on`` (see ``game.config``).
With ``off`` nothing arms, nothing starts and the autoplay guard stays silent.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .config import is_reserve_next_purchase_enabled_for, reserve_next_purchase_mode
from .db import begin_write_transaction, commit, db, is_integrity_error, rollback, table_exists

logger = logging.getLogger(__name__)

STATE_ARMED = "armed"
STATE_STARTED = "started"
STATE_CANCELLED = "cancelled"
STATE_EXPIRED = "expired"

REASON_PLAYER = "player"
REASON_REPLACED = "replaced"
REASON_SUPERSEDED = "superseded"
REASON_INVALID = "invalid"
REASON_EXPIRED = "expired"

# A forgotten reservation must not start something unwanted days later (decision D3 of the spec).
RESERVATION_TTL_SECONDS = 48 * 3600
# Ended rows are kept for the "what happened" notice and for telemetry, then pruned.
RESERVATION_RETENTION_SECONDS = 30 * 24 * 3600
RECENT_ENDED_SECONDS = 24 * 3600
_PRUNE_EVERY_SECONDS = 3600.0
_last_prune_at = 0.0

_COLUMNS = (
    "id, player_id, planet_id, building_type, expected_level, state, reason, request_id, "
    "est_cost_metal, est_cost_crystal, created_at, updated_at, expires_at, ended_at, job_id"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> Dict[str, Any]:
    keys = [k.strip() for k in _COLUMNS.split(",")]
    return {k: row[k] for k in keys}


def _exact_int(value: Any) -> int:
    try:
        return int(str(value).strip().split(".")[0] or "0")
    except (TypeError, ValueError):
        return 0


def public_view(row: Mapping[str, Any]) -> Dict[str, Any]:
    """The shape the API and the game-state payload expose (no internal columns)."""
    return {
        "id": int(row["id"]),
        "planet_id": int(row["planet_id"]),
        "building_type": str(row["building_type"]),
        "target_level": int(row["expected_level"]),
        "state": str(row["state"]),
        "reason": row["reason"],
        "est_cost_metal": str(row["est_cost_metal"]),
        "est_cost_crystal": str(row["est_cost_crystal"]),
        "created_at": float(row["created_at"]),
        "expires_at": float(row["expires_at"]),
        "ended_at": float(row["ended_at"]) if row["ended_at"] is not None else None,
        "job_id": int(row["job_id"]) if row["job_id"] is not None else None,
    }


def get_reservation(conn, reservation_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM build_reservations WHERE id = ? LIMIT 1;",
        (int(reservation_id),),
    ).fetchone()
    return _row_to_dict(row) if row else None


def get_armed_reservation(conn, planet_id: int) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM build_reservations WHERE planet_id = ? AND state = 'armed' LIMIT 1;",
        (int(planet_id),),
    ).fetchone()
    return _row_to_dict(row) if row else None


def planet_has_armed_reservation(conn, planet_id: int, player_id: Optional[int] = None) -> bool:
    """Autoplay guard: True when an enabled reservation is waiting on this planet.

    Costs nothing while the feature flag is off (no query at all), and is False on schemas that
    predate migration 189.
    """
    if reserve_next_purchase_mode() == "off":
        return False
    if not table_exists(conn, "build_reservations"):
        return False
    row = conn.execute(
        "SELECT player_id FROM build_reservations WHERE planet_id = ? AND state = 'armed' LIMIT 1;",
        (int(planet_id),),
    ).fetchone()
    if not row:
        return False
    return is_reserve_next_purchase_enabled_for(int(row["player_id"]))


def claim_reservation_in_transaction(conn, reservation_id: int, job_id: int, now: float) -> bool:
    """Compare-and-swap ``armed -> started`` inside the caller's (build) transaction. No commit."""
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE build_reservations
        SET state = 'started', reason = NULL, job_id = ?, updated_at = ?, ended_at = ?
        WHERE id = ? AND state = 'armed';
        """,
        (int(job_id), float(now), float(now), int(reservation_id)),
    )
    return cur.rowcount == 1


def _end_if_armed(reservation_id: int, state: str, reason: str, now: float) -> bool:
    """``armed -> cancelled|expired`` in its own short transaction (no resources are involved)."""
    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE build_reservations
            SET state = ?, reason = ?, updated_at = ?, ended_at = ?
            WHERE id = ? AND state = 'armed';
            """,
            (state, reason, float(now), float(now), int(reservation_id)),
        )
        changed = cur.rowcount == 1
        commit(conn)
        return changed
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# arm / cancel (player actions)
# ---------------------------------------------------------------------------


def arm_reservation(
    user_id: int,
    building_type: str,
    *,
    planet_id: Optional[int] = None,
    request_id: Optional[str] = None,
    replace: bool = False,
    now: Optional[float] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate on the server and remember the intent. Changes no stock, no queue row, no timer.

    Refusals (``ok`` False): ``disabled``, ``invalid_type``, ``no_planet``, ``not_owner``, ``vacation``,
    ``requirements``, ``max_level`` / ``ascension_required``, ``affordable_now`` (the ordinary build
    button is the right tool: a reservation would only delay it), ``reservation_exists``.
    """
    from .buildings import BASE_COST, queue_build_for_planet

    uid = int(user_id)
    ts = float(time.time() if now is None else now)
    if not is_reserve_next_purchase_enabled_for(uid):
        return False, "disabled", {}
    btype = str(building_type or "").strip()
    if btype not in BASE_COST:
        return False, "invalid_type", {}
    rid = str(request_id).strip()[:64] if request_id else ""

    conn = db()
    try:
        if not table_exists(conn, "build_reservations"):
            return False, "disabled", {}
        if planet_id is None:
            from .planet_evolution.repository import get_context_planet

            planet = get_context_planet(uid, conn=conn)
            if not planet:
                return False, "no_planet", {}
            pid = int(planet["id"])
        else:
            pid = int(planet_id)
            owner = conn.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (pid,)).fetchone()
            if not owner or int(owner["player_id"] or 0) != uid:
                return False, "not_owner", {}
        if rid:
            same = conn.execute(
                f"SELECT {_COLUMNS} FROM build_reservations WHERE player_id = ? AND request_id = ? LIMIT 1;",
                (uid, rid),
            ).fetchone()
            if same:
                return True, "ok", {"reservation": public_view(_row_to_dict(same)), "idempotent": True}
    finally:
        conn.close()

    # Every other check (cap, requirements, cost incl. the Ascension rebuild share, affordability, queue
    # slots, vacation) is the owner's own, run as a dry run so arming can never disagree with starting.
    ok, reason, info = queue_build_for_planet(
        {"id": pid, "player_id": uid}, {}, btype, user_id=uid, dry_run=True
    )
    if ok:
        return False, "affordable_now", dict(info)
    if reason == "options_error_vacation_active":
        return False, "vacation", {}
    if reason == "invalid":
        return False, "max_level", dict(info)
    if reason not in ("resources", "queue_full"):
        return False, reason, dict(info)
    target_level = int(info.get("target_level") or 0)
    if target_level <= 0:
        return False, "invalid", dict(info)

    conn = db()
    try:
        begin_write_transaction(conn)
        existing = get_armed_reservation(conn, pid)
        if existing and not replace:
            rollback(conn)
            return False, "reservation_exists", {"reservation": public_view(existing)}
        cur = conn.cursor()
        if existing:
            cur.execute(
                """
                UPDATE build_reservations
                SET state = 'cancelled', reason = ?, updated_at = ?, ended_at = ?
                WHERE id = ? AND state = 'armed';
                """,
                (REASON_REPLACED, ts, ts, int(existing["id"])),
            )
        cur.execute(
            """
            INSERT INTO build_reservations (
                player_id, planet_id, building_type, expected_level, state, request_id,
                est_cost_metal, est_cost_crystal, created_at, updated_at, expires_at
            )
            VALUES (?, ?, ?, ?, 'armed', ?, ?, ?, ?, ?, ?);
            """,
            (
                uid,
                pid,
                btype,
                target_level,
                rid or None,
                str(_exact_int(info.get("cost_metal"))),
                str(_exact_int(info.get("cost_crystal"))),
                ts,
                ts,
                ts + RESERVATION_TTL_SECONDS,
            ),
        )
        new_id = int(cur.lastrowid)
        row = get_reservation(conn, new_id)
        commit(conn)
        return True, "ok", {"reservation": public_view(row), "replaced": bool(existing)}
    except Exception as exc:
        rollback(conn)
        if is_integrity_error(exc):
            # Two simultaneous arms: the partial unique indexes decided; report the winner.
            fresh = db()
            try:
                if rid:
                    same = fresh.execute(
                        f"SELECT {_COLUMNS} FROM build_reservations WHERE player_id = ? AND request_id = ? LIMIT 1;",
                        (uid, rid),
                    ).fetchone()
                    if same:
                        return True, "ok", {"reservation": public_view(_row_to_dict(same)), "idempotent": True}
                winner = get_armed_reservation(fresh, pid)
            finally:
                fresh.close()
            return False, "reservation_exists", ({"reservation": public_view(winner)} if winner else {})
        raise
    finally:
        conn.close()


def cancel_reservation(user_id: int, reservation_id: int, *, now: Optional[float] = None) -> Tuple[bool, str, Dict[str, Any]]:
    """Free, immediate, owner-only. A STARTED reservation is cancelled through its job (queue refund rules)."""
    ts = float(time.time() if now is None else now)
    conn = db()
    try:
        if not table_exists(conn, "build_reservations"):
            return False, "disabled", {}
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE build_reservations
            SET state = 'cancelled', reason = ?, updated_at = ?, ended_at = ?
            WHERE id = ? AND player_id = ? AND state = 'armed';
            """,
            (REASON_PLAYER, ts, ts, int(reservation_id), int(user_id)),
        )
        if cur.rowcount == 1:
            row = get_reservation(conn, int(reservation_id))
            commit(conn)
            return True, "ok", {"reservation": public_view(row)}
        row = get_reservation(conn, int(reservation_id))
        rollback(conn)
        if not row or int(row["player_id"]) != int(user_id):
            return False, "not_found", {}
        return False, "not_armed", {"reservation": public_view(row)}
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# start (worker side)
# ---------------------------------------------------------------------------


def evaluate_reservation(reservation: Mapping[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
    """Try to start one armed reservation. Safe to repeat and to run from several workers at once.

    Returns ``{"outcome": ...}`` with one of: ``started``, ``waiting_funds``, ``waiting_slot``,
    ``paused`` (vacation: the reservation stays, expiry does not run), ``skipped`` (planet busy / lost a
    race: nothing to do), ``expired``, ``superseded``, ``invalid``, ``disabled``, ``error``.
    """
    from .buildings import queue_build_for_planet
    from .options import is_vacation_mode_active

    ts = float(time.time() if now is None else now)
    uid = int(reservation["player_id"])
    pid = int(reservation["planet_id"])
    rid = int(reservation["id"])
    if not is_reserve_next_purchase_enabled_for(uid):
        return {"outcome": "disabled", "reservation_id": rid}
    if is_vacation_mode_active(uid):
        return {"outcome": "paused", "reservation_id": rid}
    if ts >= float(reservation["expires_at"]):
        changed = _end_if_armed(rid, STATE_EXPIRED, REASON_EXPIRED, ts)
        return {"outcome": "expired" if changed else "skipped", "reservation_id": rid}

    ok, reason, payload = queue_build_for_planet(
        {"id": pid, "player_id": uid},
        {},
        str(reservation["building_type"]),
        user_id=uid,
        reservation={"id": rid, "expected_level": int(reservation["expected_level"])},
        lock_mode="skip",
    )
    base = {"reservation_id": rid, "planet_id": pid, "player_id": uid}
    if ok:
        return {**base, "outcome": "started", "job_id": int(payload.get("job_id") or 0)}
    if reason == "resources":
        _refresh_estimate(rid, payload)
        return {**base, "outcome": "waiting_funds"}
    if reason == "queue_full":
        _refresh_estimate(rid, payload)
        return {**base, "outcome": "waiting_slot"}
    if reason in ("lock_busy", "reservation_not_armed"):
        return {**base, "outcome": "skipped", "reason": reason}
    if reason == "options_error_vacation_active":
        return {**base, "outcome": "paused"}
    if reason == "reservation_superseded":
        # A worker that lost a race sees the winner's job as "level moved on": only the call that really
        # ended an ARMED row reports it; the loser reports "skipped".
        changed = _end_if_armed(rid, STATE_CANCELLED, REASON_SUPERSEDED, ts)
        return {**base, "outcome": "superseded" if changed else "skipped", "reason": reason}
    if reason in ("requirements", "invalid", "ascension_required"):
        changed = _end_if_armed(rid, STATE_CANCELLED, REASON_INVALID, ts)
        return {**base, "outcome": "invalid" if changed else "skipped", "reason": reason}
    logger.warning("build reservation %s: unexpected owner reason %r", rid, reason)
    return {**base, "outcome": "error", "reason": reason}


def _refresh_estimate(reservation_id: int, payload: Mapping[str, Any]) -> None:
    """Keep the (non-authoritative) pre-filter estimate in step with the price the owner just computed."""
    if "cost_metal" not in payload or "cost_crystal" not in payload:
        return
    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE build_reservations SET est_cost_metal = ?, est_cost_crystal = ?
            WHERE id = ? AND state = 'armed';
            """,
            (str(_exact_int(payload["cost_metal"])), str(_exact_int(payload["cost_crystal"])), int(reservation_id)),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        logger.exception("build reservation %s: estimate refresh failed", reservation_id)
    finally:
        conn.close()


def _candidates(conn, now: float, limit: int) -> List[Dict[str, Any]]:
    """Armed reservations worth an owner call right now (cheap pre-filter, never authoritative).

    A reservation is a candidate when it has expired (so it can be closed), or the planet holds at least
    the last known price AND a queue slot is free or about to free. The atomic debit inside the owner is
    the only authority; a wrong estimate costs one wasted call or a delay of one tick, never a wrong charge.
    """
    from .models import get_game_settings

    rows = conn.execute(
        f"""
        SELECT r.id, r.player_id, r.planet_id, r.building_type, r.expected_level, r.state, r.reason,
               r.request_id, r.est_cost_metal, r.est_cost_crystal, r.created_at, r.updated_at,
               r.expires_at, r.ended_at, r.job_id, p.metal AS planet_metal, p.crystal AS planet_crystal
        FROM build_reservations r
        JOIN planets p ON p.id = r.planet_id
        WHERE r.state = 'armed'
        ORDER BY r.updated_at ASC, r.id ASC
        LIMIT ?;
        """,
        (max(1, int(limit)) * 4,),
    ).fetchall()
    if not rows:
        return []
    pids = sorted({int(r["planet_id"]) for r in rows})
    marks = ",".join("?" for _ in pids)
    queue = {
        int(q["planet_id"]): (int(q["n"]), float(q["first_finish"]))
        for q in conn.execute(
            f"""
            SELECT planet_id, COUNT(*) AS n, MIN(finish_time) AS first_finish
            FROM build_queue WHERE planet_id IN ({marks}) GROUP BY planet_id;
            """,
            tuple(pids),
        ).fetchall()
    }
    try:
        queue_limit = max(1, int(float(get_game_settings(conn=conn).get("queue_limit", 3))))
    except (TypeError, ValueError):
        queue_limit = 3
    out: List[Dict[str, Any]] = []
    for r in rows:
        item = _row_to_dict(r)
        if now >= float(item["expires_at"]):
            out.append(item)
        else:
            metal, crystal = _exact_int(r["planet_metal"]), _exact_int(r["planet_crystal"])
            if metal < _exact_int(item["est_cost_metal"]) or crystal < _exact_int(item["est_cost_crystal"]):
                continue
            count, first_finish = queue.get(int(item["planet_id"]), (0, 0.0))
            if count >= queue_limit and first_finish > now:
                continue  # affordable but the queue is full until first_finish
            out.append(item)
        if len(out) >= limit:
            break
    return out


def prune_ended(now: float, *, batch: int = 500) -> int:
    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM build_reservations
            WHERE id IN (
                SELECT id FROM build_reservations
                WHERE state <> 'armed' AND ended_at IS NOT NULL AND ended_at < ?
                LIMIT ?
            );
            """,
            (float(now) - RESERVATION_RETENTION_SECONDS, int(batch)),
        )
        removed = int(cur.rowcount or 0)
        commit(conn)
        return removed
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def run_reservation_tick(*, now: Optional[float] = None, limit: int = 100) -> Dict[str, Any]:
    """Worker heartbeat: start what can start. Never raises (a reservation problem must not stop the queue tick)."""
    global _last_prune_at

    out: Dict[str, Any] = {"enabled": False, "evaluated": 0, "outcomes": {}, "errors": 0}
    if reserve_next_purchase_mode() == "off":
        return out
    out["enabled"] = True
    ts = float(time.time() if now is None else now)
    try:
        conn = db()
        try:
            if not table_exists(conn, "build_reservations"):
                out["enabled"] = False
                return out
            candidates = _candidates(conn, ts, int(limit))
        finally:
            conn.close()
        for item in candidates:
            try:
                result = evaluate_reservation(item, now=ts)
            except Exception:
                out["errors"] += 1
                logger.exception("build reservation %s: evaluation failed", item.get("id"))
                continue
            out["evaluated"] += 1
            name = str(result.get("outcome") or "unknown")
            out["outcomes"][name] = int(out["outcomes"].get(name, 0)) + 1
        if ts - _last_prune_at >= _PRUNE_EVERY_SECONDS:
            _last_prune_at = ts
            out["pruned"] = prune_ended(ts)
    except Exception:
        out["errors"] += 1
        logger.exception("build reservation tick failed")
    return out


# ---------------------------------------------------------------------------
# read side for the game-state payload
# ---------------------------------------------------------------------------


def planet_reservation_payload(conn, planet_id: int, player_id: int, *, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """What the buildings UI needs for one planet, or ``None`` when the feature is off for this player.

    ``armed`` carries ``waiting_for`` (``funds`` / ``slot`` / ``vacation``) so the card can say what is
    missing; ``last_ended`` is the most recent non-armed reservation of the last 24 h (so a toast can say
    what happened: started / cancelled by reason / expired).
    """
    if not is_reserve_next_purchase_enabled_for(int(player_id)):
        return None
    if not table_exists(conn, "build_reservations"):
        return None
    ts = float(time.time() if now is None else now)
    armed = get_armed_reservation(conn, int(planet_id))
    out: Dict[str, Any] = {"enabled": True, "armed": None, "last_ended": None, "ttl_seconds": RESERVATION_TTL_SECONDS}
    if armed:
        view = public_view(armed)
        pl = conn.execute("SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),)).fetchone()
        waiting = "slot"
        if pl and (
            _exact_int(pl["metal"]) < _exact_int(armed["est_cost_metal"])
            or _exact_int(pl["crystal"]) < _exact_int(armed["est_cost_crystal"])
        ):
            waiting = "funds"
        try:
            from .options import is_vacation_mode_active

            if is_vacation_mode_active(int(player_id), conn=conn):
                waiting = "vacation"
        except Exception:
            pass
        view["waiting_for"] = waiting
        out["armed"] = view
    ended = conn.execute(
        f"""
        SELECT {_COLUMNS} FROM build_reservations
        WHERE planet_id = ? AND state <> 'armed' AND ended_at IS NOT NULL AND ended_at >= ?
        ORDER BY ended_at DESC, id DESC LIMIT 1;
        """,
        (int(planet_id), ts - RECENT_ENDED_SECONDS),
    ).fetchone()
    if ended:
        out["last_ended"] = public_view(_row_to_dict(ended))
    return out
