"""Authenticated player-presence hot path.

GC-PG-HIGHSPEED-001C makes PostgreSQL ``player_presence`` the canonical hot
presence store. While remaining readers are cut over, ``players.last_seen`` is
kept as a low-frequency compatibility mirror (max once per four minutes).

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
from .presence_store import (
    get_presence_last_seen,
    should_sync_legacy_last_seen,
    sync_legacy_last_seen,
    touch_presence,
)

logger = logging.getLogger(__name__)


def _run_optional_savepoint(conn, *, name: str, callback, failure_message: str, player_id: int) -> None:  # noqa: ANN001
    """Run optional PostgreSQL work without poisoning the owning presence TX."""
    conn.execute(f"SAVEPOINT {name}")
    try:
        callback()
        conn.execute(f"RELEASE SAVEPOINT {name}")
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            conn.execute(f"RELEASE SAVEPOINT {name}")
        except Exception:
            raise
        logger.warning(failure_message, int(player_id), exc_info=True)


def _release_roster_optional(conn, player_id: int, *, backend: str) -> None:  # noqa: ANN001
    """Release inactive-autoplay ownership without poisoning presence writes."""
    from .inactive_autoplay import release_active_player_from_roster

    if backend != "postgres":
        try:
            release_active_player_from_roster(int(player_id), conn=conn)
        except Exception:
            logger.warning(
                "release_active_player_from_roster failed player=%s",
                int(player_id),
                exc_info=True,
            )
        return

    _run_optional_savepoint(
        conn,
        name="gc_presence_roster",
        callback=lambda: release_active_player_from_roster(int(player_id), conn=conn),
        failure_message=(
            "release_active_player_from_roster failed player=%s — presence preserved"
        ),
        player_id=int(player_id),
    )


def _sync_legacy_presence_optional(conn, player_id: int, *, now: int, backend: str) -> None:  # noqa: ANN001
    """Keep legacy readers fresh without making players the hot presence owner."""
    if backend != "postgres":
        return
    _run_optional_savepoint(
        conn,
        name="gc_presence_legacy",
        callback=lambda: sync_legacy_last_seen(conn, int(player_id), now=int(now)),
        failure_message=(
            "legacy last_seen mirror skipped player=%s — dedicated presence preserved"
        ),
        player_id=int(player_id),
    )


def _legacy_last_seen_for_mirror(conn, player_id: int) -> int:  # noqa: ANN001
    """Read only the compatibility timestamp; never lock the players row."""
    row = conn.execute(
        "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ? LIMIT 1;",
        (int(player_id),),
    ).fetchone()
    return int(row["last_seen"] or 0) if row else 0


def touch_player_online(player_id: int) -> None:
    """Mark a real authenticated player online using dedicated PG presence."""
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
        previous_seen = get_presence_last_seen(conn, pid, backend=backend)
        need_last_seen = previous_seen < touch_before

        # The compatibility mirror has its own cadence. Driving this from the
        # dedicated timestamp would keep an actively polling player's
        # players.last_seen stale forever after the first mirror write.
        legacy_seen = (
            _legacy_last_seen_for_mirror(conn, pid) if backend == "postgres" else previous_seen
        )
        need_legacy_sync = backend == "postgres" and should_sync_legacy_last_seen(
            previous_seen=legacy_seen,
            now=now,
        )

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

        if not need_last_seen and not need_roster and not need_legacy_sync:
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
        if need_legacy_sync:
            _sync_legacy_presence_optional(conn, pid, now=now, backend=backend)
        _release_roster_optional(conn, pid, backend=backend)
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
