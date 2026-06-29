"""Special resources, trade routes, and import deficits."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import get_game_settings
from .definitions import get_chain, get_special_resource_def
from .mechanics import get_flag
from .repository import (
    get_import_demands,
    get_planet_mechanics,
    get_planet_row,
    get_production_chains,
    get_special_resources,
    get_trade_routes,
)


def ensure_special_resource_row(
    planet_id: int,
    resource_key: str,
    conn: sqlite3.Connection,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT 1 FROM planet_special_resources
        WHERE planet_id = ? AND resource_key = ? LIMIT 1;
        """,
        (int(planet_id), str(resource_key)),
    )
    if cur.fetchone():
        return
    rdef = get_special_resource_def(resource_key) or {}
    cap = float(rdef.get("base_cap") or 100000)
    cur.execute(
        """
        INSERT INTO planet_special_resources (
            planet_id, resource_key, amount, cap, production_per_hour, consumption_per_hour
        ) VALUES (?, ?, 0, ?, 0, 0);
        """,
        (int(planet_id), str(resource_key), cap),
    )


def _chain_output_bonus_factor(
    planet_id: int,
    chain_key: str,
    output_key: str,
    conn: sqlite3.Connection,
) -> float:
    """
    Additive fractional bonus from compiled planet mechanics.

    Format (canonical):
    - dict: per chain_key or output_resource_key, e.g. {"refined_ferronit": 0.15} → +15 %
    - scalar: applies to all chains, e.g. 0.20 → +20 % (policy mandatory_overtime)

    Distinct from chain_output_mult, which is a direct multiplier (e.g. 1.4).
    """
    bonus = get_flag(planet_id, "chain_output_bonus", None, conn=conn)
    if bonus is None:
        return 1.0
    if isinstance(bonus, dict):
        additive = bonus.get(chain_key)
        if additive is None:
            additive = bonus.get(output_key)
        if additive is None:
            return 1.0
        return 1.0 + float(additive)
    if isinstance(bonus, (int, float)):
        return 1.0 + float(bonus)
    return 1.0


def _culture_chain_mult(planet_id: int, chain_key: str, conn: sqlite3.Connection, *, output_key: str = "") -> float:
    from .repository import get_planet_culture

    culture = get_planet_culture(planet_id, conn=conn)
    mult = 1.0
    stability = float(culture.get("stability") or 70)
    if stability < 30:
        mult *= 0.5
    if stability < 15:
        mult *= 0.0
    crime = float(culture.get("crime") or 0)
    planet = get_planet_row(planet_id, conn=conn) or {}
    if str(planet.get("specialization_key") or "") == "smuggler_colony" and 40 <= crime <= 70:
        if chain_key == "contraband":
            mult *= 2.0
    bonus = get_flag(planet_id, "chain_output_mult", None, conn=conn)
    if bonus:
        mult *= float(bonus)
    mult *= _chain_output_bonus_factor(
        planet_id,
        chain_key,
        output_key or chain_key,
        conn,
    )
    return mult


def compute_import_deficits(
    planet_id: int,
    conn: sqlite3.Connection,
    *,
    delta_hours: float = 1.0,
) -> List[Dict[str, Any]]:
    demands = get_import_demands(planet_id, conn=conn)
    if not demands:
        return []

    resources = {str(r["resource_key"]): r for r in get_special_resources(planet_id, conn=conn)}
    routes_in = _incoming_routes(planet_id, conn)
    deficits: List[Dict[str, Any]] = []

    for demand in demands:
        key = str(demand["resource_key"])
        required = float(demand["required_per_hour"]) * float(delta_hours)
        received = float(routes_in.get(key, 0.0)) * float(delta_hours)
        local = float((resources.get(key) or {}).get("production_per_hour") or 0) * float(delta_hours)
        total = received + local
        if total + 1e-6 < required:
            deficits.append(
                {
                    "resource_key": key,
                    "required_per_hour": float(demand["required_per_hour"]),
                    "received_per_hour": received / max(delta_hours, 1e-6),
                    "deficit_per_hour": float(demand["required_per_hour"]) - (total / max(delta_hours, 1e-6)),
                    "deficit_penalty_key": str(demand.get("deficit_penalty_key") or "chain_efficiency_halved"),
                }
            )
    return deficits


def _incoming_routes(planet_id: int, conn: sqlite3.Connection) -> Dict[str, float]:
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    owner_row = cur.fetchone()
    owner_id = int(owner_row["player_id"]) if owner_row else None
    if owner_id is None:
        return {}

    cur.execute(
        """
        SELECT resource_key, SUM(amount_per_hour) AS total
        FROM planet_trade_routes
        WHERE target_planet_id = ? AND owner_player_id = ? AND is_active = 1
        GROUP BY resource_key;
        """,
        (int(planet_id), owner_id),
    )
    return {str(r["resource_key"]): float(r["total"] or 0) for r in cur.fetchall()}


def _consume_planet_inputs(
    planet_id: int,
    inputs: Dict[str, Any],
    delta_hours: float,
    conn: sqlite3.Connection,
) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    prow = cur.fetchone()
    if not prow:
        return False

    metal_need = float(inputs.get("metal") or 0) * delta_hours
    crystal_need = float(inputs.get("crystal") or 0) * delta_hours
    metal = float(prow["metal"] or 0)
    crystal = float(prow["crystal"] or 0)
    if metal < metal_need or crystal < crystal_need:
        return False

    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (metal - metal_need, crystal - crystal_need, int(planet_id)),
    )
    return True


def _add_special_amount(
    planet_id: int,
    resource_key: str,
    amount: float,
    conn: sqlite3.Connection,
) -> None:
    ensure_special_resource_row(planet_id, resource_key, conn)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planet_special_resources
        SET amount = MIN(cap, MAX(0, amount + ?))
        WHERE planet_id = ? AND resource_key = ?;
        """,
        (float(amount), int(planet_id), str(resource_key)),
    )


def tick_special_resources(
    planet_id: int,
    delta_hours: float,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    if delta_hours <= 0:
        return {"produced": {}}

    from .failures import active_failure_keys

    failures = active_failure_keys(planet_id, conn)
    if "reactor_crisis" in failures or "population_crisis" in failures:
        return {"produced": {}, "halted": "failure"}

    deficits = {d["resource_key"]: d for d in compute_import_deficits(planet_id, conn, delta_hours=delta_hours)}
    chains = get_production_chains(planet_id, conn=conn)
    produced: Dict[str, float] = {}

    for chain_row in chains:
        if not int(chain_row.get("is_active") or 0):
            continue
        chain_key = str(chain_row["chain_key"])
        chain = get_chain(chain_key)
        if not chain:
            continue

        output_key = str(chain.get("output_resource_key") or chain_key)
        for res_key in (chain.get("inputs") or {}).keys():
            if res_key in deficits:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE planet_production_chains SET efficiency = 0.5 WHERE planet_id = ? AND chain_key = ?;",
                    (int(planet_id), chain_key),
                )
                continue

        efficiency = float(chain_row.get("efficiency") or 1.0)
        if chain_key in deficits or output_key in deficits:
            efficiency *= 0.5

        inputs = chain.get("inputs") or {}
        if inputs and not _consume_planet_inputs(planet_id, inputs, delta_hours, conn):
            cur = conn.cursor()
            cur.execute(
                "UPDATE planet_production_chains SET efficiency = 0 WHERE planet_id = ? AND chain_key = ?;",
                (int(planet_id), chain_key),
            )
            continue

        base_out = float(chain.get("base_output_per_hour") or 0)
        mult = _culture_chain_mult(planet_id, chain_key, conn, output_key=output_key)
        output = base_out * efficiency * mult * float(delta_hours)
        if output <= 0:
            continue

        _add_special_amount(planet_id, output_key, output, conn)
        produced[output_key] = produced.get(output_key, 0.0) + output

        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planet_production_chains
            SET last_tick_at = ?, efficiency = MIN(1.0, MAX(0.25, efficiency))
            WHERE planet_id = ? AND chain_key = ?;
            """,
            (time.time(), int(planet_id), chain_key),
        )

    _apply_decay(planet_id, delta_hours, conn)
    return {"produced": produced, "deficits": list(deficits.values())}


def _apply_decay(planet_id: int, delta_hours: float, conn: sqlite3.Connection) -> None:
    try:
        settings = get_game_settings(conn=conn)
        global_decay = float(settings.get("special_resource_decay_global", 0.02))
    except Exception:
        global_decay = 0.02

    day_frac = float(delta_hours) / 24.0
    rows = get_special_resources(planet_id, conn=conn)
    cur = conn.cursor()
    for row in rows:
        key = str(row["resource_key"])
        rdef = get_special_resource_def(key) or {}
        decay = float(rdef.get("decay_per_day") or global_decay)
        cap = float(row["cap"] or 1)
        amount = float(row["amount"] or 0)
        soft = cap * 0.8
        if amount <= soft:
            continue
        excess = amount - soft
        loss = excess * decay * day_frac
        cur.execute(
            """
            UPDATE planet_special_resources SET amount = MAX(0, amount - ?)
            WHERE planet_id = ? AND resource_key = ?;
            """,
            (loss, int(planet_id), key),
        )


def process_trade_routes(
    planet_id: int,
    delta_hours: float,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    if delta_hours <= 0:
        return {"transfers": []}

    planet = get_planet_row(planet_id, conn=conn) or {}
    owner = planet.get("player_id")
    if not owner:
        return {"transfers": []}

    routes = [
        r
        for r in get_trade_routes(int(owner), conn=conn)
        if int(r.get("source_planet_id") or 0) == int(planet_id) and int(r.get("is_active") or 0)
    ]
    transfers: List[Dict[str, Any]] = []
    bonus = float(get_flag(planet_id, "trade_route_bonus", 0.0, conn=conn) or 0.0)

    for route in routes:
        amount_h = float(route["amount_per_hour"]) * (1.0 + bonus)
        amount = amount_h * float(delta_hours)
        resource_key = str(route["resource_key"])
        target_id = int(route["target_planet_id"])

        if resource_key in ("metal", "crystal"):
            cur = conn.cursor()
            cur.execute("SELECT metal, crystal FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
            src = cur.fetchone()
            if not src:
                continue
            col = resource_key
            available = float(src[col] or 0)
            move = min(available, amount)
            if move <= 0:
                continue
            cur.execute(
                f"UPDATE planets SET {col} = {col} - ? WHERE id = ?;",
                (move, int(planet_id)),
            )
            cur.execute(
                f"UPDATE planets SET {col} = {col} + ? WHERE id = ?;",
                (move, target_id),
            )
            transfers.append({"resource_key": resource_key, "amount": move, "target_planet_id": target_id})
        else:
            ensure_special_resource_row(planet_id, resource_key, conn)
            ensure_special_resource_row(target_id, resource_key, conn)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT amount FROM planet_special_resources
                WHERE planet_id = ? AND resource_key = ? LIMIT 1;
                """,
                (int(planet_id), resource_key),
            )
            row = cur.fetchone()
            available = float(row["amount"] or 0) if row else 0.0
            move = min(available, amount)
            if move <= 0:
                continue
            cur.execute(
                """
                UPDATE planet_special_resources SET amount = amount - ?
                WHERE planet_id = ? AND resource_key = ?;
                """,
                (move, int(planet_id), resource_key),
            )
            cur.execute(
                """
                UPDATE planet_special_resources
                SET amount = MIN(cap, amount + ?)
                WHERE planet_id = ? AND resource_key = ?;
                """,
                (move, target_id, resource_key),
            )
            transfers.append({"resource_key": resource_key, "amount": move, "target_planet_id": target_id})

    return {"transfers": transfers}
