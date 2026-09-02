"""Transaction-safe optional Stellar Forge gameplay hooks.

These hooks are called from larger caller-owned PostgreSQL transactions (fleet,
world boss, etc.).  A caught PostgreSQL statement error still marks that outer
transaction aborted, so optional Forge writes must recover through a SAVEPOINT
before returning control to the caller.
"""

from __future__ import annotations

from typing import Any, Optional

from ..db import get_db_backend, is_db_lock_error
from .service import record_operational_progress as _record_operational_progress


def record_operational_progress(
    planet_id: int,
    protocol: str,
    amount: float,
    *,
    conn: Any,
    now: Optional[float] = None,
) -> None:
    """Record optional Forge progress without poisoning a caller-owned PG tx.

    PostgreSQL changes a transaction to ``INERROR`` after a lock timeout.  The
    fleet/world-boss callers intentionally treat Forge progress as best-effort,
    but simply catching that exception is insufficient: every later statement
    would fail with ``InFailedSqlTransaction``.  Keep the optional write behind
    a savepoint and roll back only that hook on transient DB lock contention.

    Non-lock failures are re-raised *after* restoring the parent transaction so
    existing callers retain their normal error handling without inheriting an
    aborted connection.
    """
    if get_db_backend() != "postgres":
        _record_operational_progress(planet_id, protocol, amount, conn=conn, now=now)
        return

    savepoint = "gc_stellar_forge_operational_progress"
    conn.execute(f"SAVEPOINT {savepoint};")
    try:
        _record_operational_progress(planet_id, protocol, amount, conn=conn, now=now)
    except Exception as exc:
        # ROLLBACK TO SAVEPOINT is deliberately used instead of conn.rollback():
        # the outer fleet/world-boss transaction belongs to the caller.
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
        if is_db_lock_error(exc):
            return
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
