"""Authenticated player-presence hot path.

Issue #142: keep presence best-effort without nested PostgreSQL pool checkouts.

The legacy implementation in ``game.models.touch_player_online`` attempted a
second ``db()`` checkout from its lock-error handler before releasing the first
connection. Under sustained player-row contention that can turn a harmless
250 ms presence soft-fail into pool starvation: many request threads each hold
one checkout while waiting for another.

This module is the request-guard owner for presence. It preserves existing
last_seen throttling and inactive-autoplay handback semantics on the successful
path, but a lock soft-fail rolls back and returns using the *same* checkout. The
next authenticated request retries normally because the local freshness marker
is not advanced on a failed write.
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

logger = logging.getLogger(__name__)


def touch_player_online(player_id: int) -> None:
    """Mark a real authenticated player online without nested DB checkouts.

    Presence remains best-effort. Successful writes keep the existing
    ``players.last_seen`` cadence and release a returning human from inactive
    autoplay in the same short transaction. PostgreSQL lock contention is a
    soft skip; no retry/pool/timeout defaults are changed.
    """
    if not player_id:
        return

    # Reuse the existing process-local throttle and configured cadence so this
    # is behavior-compatible while 001C dedicated presence storage is prepared.
    from . import models

    pid = int(player_id)
    now = int(models._now_ts())
    interval = int(models._presence_touch_interval_sec())
    touch_before = now - interval

    if models._presence_local_fresh(pid, now=now):
        return

    conn = db()
    try:
        row = conn.execute(
            "SELECT last_seen FROM players WHERE id = ? LIMIT 1;",
            (pid,),
        ).fetchone()
        last_seen = int(row["last_seen"] or 0) if row else 0
        need_last_seen = last_seen < touch_before

        need_roster = False
        try:
            from .inactive_autoplay import player_on_inactive_autoplay_roster

            need_roster = bool(player_on_inactive_autoplay_roster(pid, conn=conn))
        except Exception:
            # Preserve prior fail-open behavior: if we cannot prove the player
            # is off the roster, run the normal short write slice.
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
        if get_db_backend() == "postgres":
            conn.execute("SET LOCAL lock_timeout = '250ms'")

        conn.execute(
            "UPDATE players SET last_seen = ? "
            "WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
            (now, pid, touch_before),
        )

        from .inactive_autoplay import release_active_player_from_roster

        release_active_player_from_roster(pid, conn=conn)
        commit(conn)
        models._presence_local_mark(pid, now=now, interval=interval)
    except Exception as exc:
        try:
            rollback(conn)
        except Exception:
            pass

        if is_db_lock_error(exc):
            # Critical #142 invariant: DO NOT open another connection here.
            # The failed touch is retried by a later authenticated request.
            logger.warning(
                "touch_player_online locked player=%s — best-effort skip without nested checkout",
                pid,
            )
            return
        logger.exception("touch_player_online failed player=%s", pid)
        raise
    finally:
        conn.close()
