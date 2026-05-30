"""Scrapyard — recycle ships on the active planet for partial resource refund."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Tuple

from .db import begin_write_transaction, commit, db, rollback
from .fleet import deduct_planet_ships, get_planet_ships
from .fleet_defs import canonical_ship_key, get_ship, is_known_ship_key
from .models import lock_planet_for_update
from .shipyard import _unit_build_cost

SCRAP_REFUND_MIN = 0.50
SCRAP_REFUND_MAX = 0.75


def scrap_refund_ratio(*, seed: int | None = None) -> float:
    rng = random.Random(seed) if seed is not None else random
    return SCRAP_REFUND_MIN + (SCRAP_REFUND_MAX - SCRAP_REFUND_MIN) * rng.random()


def scrap_value_for_ship(ship_key: str, amount: int, *, ratio: float) -> Dict[str, int]:
    sk = canonical_ship_key(ship_key)
    cost = _unit_build_cost(sk)
    qty = max(0, int(amount))
    r = max(SCRAP_REFUND_MIN, min(SCRAP_REFUND_MAX, float(ratio)))
    return {
        "metal": int(cost["metal"] * qty * r),
        "crystal": int(cost["crystal"] * qty * r),
        "fuel_cells": int(cost["fuel_cells"] * qty * r),
    }


def list_scrapyard_ships(player_id: int, planet_id: int, *, conn=None) -> List[Dict[str, Any]]:
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
            return []
        ships = get_planet_ships(int(planet_id), conn=conn)
        out: List[Dict[str, Any]] = []
        for key, qty in sorted(ships.items()):
            if int(qty) <= 0:
                continue
            spec = get_ship(key) or {}
            cost = _unit_build_cost(key)
            out.append(
                {
                    "ship_key": key,
                    "amount": int(qty),
                    "role": spec.get("role"),
                    "build_cost": cost,
                    "preview_refund_min": scrap_value_for_ship(key, int(qty), ratio=SCRAP_REFUND_MIN),
                    "preview_refund_max": scrap_value_for_ship(key, int(qty), ratio=SCRAP_REFUND_MAX),
                }
            )
        return out
    finally:
        if own and conn is not None:
            conn.close()


def recycle_ships(
    *,
    player_id: int,
    planet_id: int,
    ship_key: str,
    amount: int,
    conn=None,
) -> Tuple[bool, str, Dict[str, Any] | None]:
    sk = canonical_ship_key(ship_key)
    if not is_known_ship_key(sk):
        return False, "unknown_ship", None
    try:
        qty = int(amount)
    except (TypeError, ValueError):
        return False, "invalid_amount", None
    if qty <= 0:
        return False, "invalid_amount", None

    own = conn is None
    if own:
        conn = db()
    try:
        if own:
            begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        cur = conn.cursor()
        cur.execute(
            "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        if not cur.fetchone():
            if own:
                rollback(conn)
            return False, "planet_not_found", None

        have = int(get_planet_ships(int(planet_id), conn=conn).get(sk, 0))
        if qty > have:
            if own:
                rollback(conn)
            return False, "not_enough_ships", None

        ratio = scrap_refund_ratio()
        refund = scrap_value_for_ship(sk, qty, ratio=ratio)
        ok, reason = deduct_planet_ships(int(planet_id), {sk: qty}, conn=conn)
        if not ok:
            if own:
                rollback(conn)
            return False, reason, None

        if refund["metal"] or refund["crystal"] or refund["fuel_cells"]:
            cur.execute(
                """
                UPDATE planets
                SET metal = metal + ?,
                    crystal = crystal + ?,
                    fuel_cells = fuel_cells + ?
                WHERE id = ?;
                """,
                (
                    refund["metal"],
                    refund["crystal"],
                    float(refund["fuel_cells"]),
                    int(planet_id),
                ),
            )

        if own:
            commit(conn)

        return True, "", {
            "ship_key": sk,
            "amount": qty,
            "refund_ratio": round(ratio, 4),
            "refund": refund,
            "ships": get_planet_ships(int(planet_id), conn=conn),
        }
    except Exception:
        if own:
            rollback(conn)
        raise
    finally:
        if own and conn is not None:
            conn.close()


def scrapyard_status(player_id: int, planet_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
            (int(planet_id), int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            return {"ready": False}
        planet = dict(row)
        return {
            "ready": True,
            "planet_id": int(planet_id),
            "refund_min_percent": int(SCRAP_REFUND_MIN * 100),
            "refund_max_percent": int(SCRAP_REFUND_MAX * 100),
            "ships": list_scrapyard_ships(player_id, planet_id, conn=conn),
            "resources": {
                "metal": int(float(planet["metal"] or 0)),
                "crystal": int(float(planet["crystal"] or 0)),
                "fuel_cells": int(float(planet["fuel_cells"] or 0)),
            },
        }
    finally:
        if own and conn is not None:
            conn.close()
