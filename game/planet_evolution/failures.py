"""Planet failure states and recovery ticks."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Set

from .history import append_history
from .mechanics import compile_planet_mechanics
from .repository import _json_dumps


FAILURE_DURATIONS_HOURS: Dict[str, float] = {
    "reactor_degraded": 48,
    "reactor_crisis": 48,
    "research_containment_breach": 168,
    "corruption_scandal": 120,
    "smuggling_crackdown": 72,
    "ai_runaway": 96,
    "stability_collapse": 72,
    "population_crisis": 96,
    "resource_depletion": 240,
    "quantum_instability": 168,
}

FAILURE_AGGREGATE: Dict[str, str] = {
    "reactor_crisis": "crisis",
    "stability_collapse": "crisis",
    "population_crisis": "crisis",
    "ai_runaway": "crisis",
    "research_containment_breach": "degraded",
    "reactor_degraded": "degraded",
    "smuggling_crackdown": "degraded",
    "corruption_scandal": "degraded",
    "resource_depletion": "degraded",
    "quantum_instability": "degraded",
}


def active_failure_keys(planet_id: int, conn: sqlite3.Connection) -> Set[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT failure_key FROM planet_failure_states
        WHERE planet_id = ? AND state IN ('active','recovering');
        """,
        (int(planet_id),),
    )
    return {str(r["failure_key"]) for r in cur.fetchall()}


def _sync_aggregate_failure_state(planet_id: int, conn: sqlite3.Connection) -> None:
    active = active_failure_keys(planet_id, conn)
    worst = None
    for key in active:
        state = FAILURE_AGGREGATE.get(key)
        if state == "crisis":
            worst = "crisis"
            break
        if state == "degraded" and worst != "crisis":
            worst = "degraded"
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET failure_state = ? WHERE id = ?;",
        (worst, int(planet_id)),
    )


def apply_failure(
    planet_id: int,
    failure_key: str,
    conn: sqlite3.Connection,
    *,
    duration_hours: Optional[float] = None,
    effects: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = time.time()
    duration = float(
        duration_hours
        if duration_hours is not None
        else FAILURE_DURATIONS_HOURS.get(str(failure_key), 72)
    )
    resolve_at = now + duration * 3600

    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM planet_failure_states
        WHERE planet_id = ? AND failure_key = ? AND state IN ('active','recovering')
        LIMIT 1;
        """,
        (int(planet_id), str(failure_key)),
    )
    if cur.fetchone():
        return {"applied": False, "reason": "already_active"}

    cur.execute(
        """
        INSERT INTO planet_failure_states (
            planet_id, failure_key, state, started_at, resolve_at, effects_json
        ) VALUES (?, ?, 'active', ?, ?, ?);
        """,
        (int(planet_id), str(failure_key), now, resolve_at, _json_dumps(effects or {})),
    )

    append_history(
        planet_id,
        "failure",
        f"failure_{failure_key}",
        history_tag=f"failure_{failure_key}",
        payload={"failure_key": failure_key, "resolve_at": resolve_at},
        conn=conn,
    )
    _sync_aggregate_failure_state(planet_id, conn)
    compile_planet_mechanics(planet_id, conn)
    return {"applied": True, "failure_key": failure_key, "resolve_at": resolve_at}


def recover_failures(conn: sqlite3.Connection, planet_id: int, now: float) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM planet_failure_states
        WHERE planet_id = ? AND state IN ('active','recovering')
          AND resolve_at IS NOT NULL AND resolve_at <= ?;
        """,
        (int(planet_id), float(now)),
    )
    rows = cur.fetchall()
    recovered = 0
    for row in rows:
        failure_key = str(row["failure_key"])
        cur.execute(
            "UPDATE planet_failure_states SET state = 'resolved' WHERE id = ?;",
            (int(row["id"]),),
        )
        append_history(
            planet_id,
            "failure_recovered",
            f"failure_recovered_{failure_key}",
            history_tag=f"survived_{failure_key}",
            payload={"failure_key": failure_key},
            conn=conn,
        )
        recovered += 1

    if recovered:
        _sync_aggregate_failure_state(planet_id, conn)
        compile_planet_mechanics(planet_id, conn)
    return recovered
