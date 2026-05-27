"""Evolution tick orchestration (culture, economy, events)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..models import db
from .ascension import finish_ascension_jobs
from .bootstrap import ensure_planet_evolution
from .culture import apply_culture_drift
from .economy import process_trade_routes, tick_special_resources
from .events import PlanetEventEngine
from .failures import recover_failures
from .planet_research import finish_planet_research_jobs
from .repository import get_planet_row


def evolution_tick_planet(
    conn: sqlite3.Connection,
    planet_id: int,
    now: float,
    *,
    skip_research_finish: bool = False,
) -> Dict[str, Any]:
    ensure_planet_evolution(planet_id, conn)
    planet = get_planet_row(planet_id, conn=conn) or {}
    last = float(planet.get("last_evolution_tick") or now)
    delta_h = max(0.0, (float(now) - last) / 3600.0)

    result: Dict[str, Any] = {
        "planet_id": int(planet_id),
        "delta_hours": delta_h,
        "skipped": delta_h < 0.01,
    }
    if delta_h < 0.01:
        return result

    if not skip_research_finish:
        result["planet_research_finished"] = finish_planet_research_jobs(conn, planet_id, now)
        result["ascension_finished"] = finish_ascension_jobs(conn, planet_id, now)
    result["failures_recovered"] = recover_failures(conn, planet_id, now)
    result["culture"] = apply_culture_drift(conn, planet_id, delta_h)
    result["special_resources"] = tick_special_resources(planet_id, delta_h, conn)
    result["trade_routes"] = process_trade_routes(planet_id, delta_h, conn)
    result["events"] = PlanetEventEngine.tick_planet(conn, planet_id, now)

    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET last_evolution_tick = ? WHERE id = ?;",
        (float(now), int(planet_id)),
    )
    return result


def evolution_tick_batch(
    planet_ids: List[int],
    now: Optional[float] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    ts = float(now if now is not None else time.time())
    own = conn is None
    if own:
        conn = db()
    try:
        results = []
        for pid in planet_ids:
            results.append(evolution_tick_planet(conn, int(pid), ts))
        if own:
            conn.commit()
        return {"ok": True, "now": ts, "count": len(results), "planets": results}
    finally:
        if own and conn is not None:
            conn.close()
