"""Authenticated player-presence hot path.

GC-PG-HIGHSPEED-001C moves PostgreSQL online touches off the hot ``players``
gameplay row into ``player_presence``. SQLite intentionally keeps the legacy
storage path for local/backward compatibility.

Presence stays best-effort, single-checkout, short-transaction work. A lock
soft-fail never asks the pool for a second connection.
"""

from __future__ import annotations

import logging

from .db import (
    begin_write_transaction,
    commit,
    db,
    get_db_backend,
    is_db_lock_error,
    rollback,
)
from .presence_store import get_presence_last_seen, touch_presence

logger = logging.getLogger(__name__)


def _release_roster_optional(conn, player_id: int) -> None:  # noqa: ANN001
    """Release inactive-autoplay ownership without poisoning presence writes.

    PostgreSQL aborts the transaction after a failed statement. Scope this
    optional side effect to a SAVEPOINT so a runtime-state failure cannot roll
    back an already-successful presence-table write. SQLite keeps the established
    fail-open behavior. No foreign transaction is committed or blanket-rolled
    back here.
    """
    from .inactive_autoplay import release_active_player_from_roster

    if get_db_backend() != "postgres":
        try:
            release_active_player_from_roster(int(player_id), conn=conn)
        except Exception:
            logger.warning(
                "release_active_player_from_roster failed player=%s",
                int(player_id),
                exc_info=True,
            )
        return

    savepoint = "gc_presence_roster"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        release_active_player_from_roster(int(player_id), conn=conn)
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            raise
        logger.warning(
            "release_active_player_from_roster failed player=%s — presence preserved",
            int(player_id),
            exc_info=True,
        )


def touch_player_online(player_id: int) -> None:
    """Mark a real authenticated player online without hot player-row writes."""
    if not player_id:
        return

    from . import models

    pid = int(player_id)
    now = int(models._now_ts())
    interval = int(models._presence_touch_interval_sec())
    touch_before = now - interval

    if models._presence_local_fresh(pid, now=now):
        return

    backend = get_db_backend()
    conn = db()
    try:
        # On PostgreSQL this SELECT only touches player_presence. A gameplay
        # transaction may hold the players row without stalling auth presence.
        last_seen = get_presence_last_seen(conn, pid, backend=backend)
        need_last_seen = last_seen < touch_before

        need_roster = False
        try:
            from .inactive_autoplay import player_on_inactive_autoplay_roster

            need_roster = bool(player_on_inactive_autoplay_roster(pid, conn=conn))
        except Exception:
            need_roster = True
            logger.warning(
                "player_on_inactive_autoplay_roster probe failed player=%s",
                pid,
                exc_info=True,
            )

        if not need_last_seen and not need_roster:
            models._presence_local_mark(pid, now=now, interval=interval)
            return

        begin_write_transaction(conn)
        if backend == "postgres":
            conn.execute("SET LOCAL lock_timeout = '250ms'")

        touch_presence(
            conn,
            pid,
            now=now,
            touch_before=touch_before,
            backend=backend,
        )
        _release_roster_optional(conn, pid)
        commit(conn)
        models._presence_local_mark(pid, now=now, interval=interval)
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass

        if is_db_lock_error(exc):
            logger.warning(
                "touch_player_online locked player=%s — best-effort skip without nested checkout",
                pid,
            )
            return
        logger.exception("touch_player_online failed player=%s", pid)
        raise
    finally:
        conn.close()
