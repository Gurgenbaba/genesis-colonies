"""Transaction-safe optional Stellar Forge gameplay hooks.

These hooks are called from larger caller-owned PostgreSQL transactions (fleet,
world boss, etc.). A caught PostgreSQL statement error still marks that outer
transaction aborted, so optional Forge writes must recover through a SAVEPOINT
before returning control to the caller.
"""

from __future__ import annotations

from typing import Any, Optional

from ..db import get_db_backend, is_db_lock_error
from .service import record_operational_progress as _record_operational_progress


def _is_aborted_transaction_error(exc: BaseException) -> bool:
    """Recognize PostgreSQL's failed-transaction sentinel without psycopg imports."""
    name = type(exc).__name__
    if name == "InFailedSqlTransaction":
        return True
    msg = str(exc).lower()
    return (
        "current transaction is aborted" in msg
        or "commands ignored until end of transaction block" in msg
    )


def _rollback_optional_savepoint(conn: Any, savepoint: str) -> None:
    """Recover only the optional hook subtransaction, never the caller's tx."""
    conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
    conn.execute(f"RELEASE SAVEPOINT {savepoint};")


def record_operational_progress(
    planet_id: int,
    protocol: str,
    amount: int,
    *,
    conn: Any,
    now: Optional[float] = None,
) -> None:
    """Record optional Forge progress without poisoning a caller-owned PG tx.

    PostgreSQL changes a transaction to ``INERROR`` after a lock timeout. The
    fleet/world-boss callers intentionally treat Forge progress as best-effort,
    but simply catching that exception is insufficient: every later statement
    would fail with ``InFailedSqlTransaction``. Keep the optional write behind
    a savepoint and roll back only that hook on transient DB lock contention.

    Some Stellar Forge schema guards intentionally swallow DB errors and return
    normally. PostgreSQL still leaves the savepoint subtransaction in ``INERROR``
    in that case, so even the success path must recover if ``RELEASE SAVEPOINT``
    reports an aborted transaction.

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
        _rollback_optional_savepoint(conn, savepoint)
        if is_db_lock_error(exc):
            return
        raise

    try:
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
    except Exception as exc:
        # A schema/table guard inside the wrapped service can catch a statement
        # error and return False. In PostgreSQL that swallowed error still marks
        # this subtransaction failed, so RELEASE itself becomes the first visible
        # InFailedSqlTransaction. Recover the savepoint and soft-skip the optional
        # progress write instead of poisoning the parent fleet/world-boss tx.
        if not _is_aborted_transaction_error(exc):
            raise
        _rollback_optional_savepoint(conn, savepoint)
