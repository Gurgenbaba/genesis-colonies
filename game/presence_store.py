"""GC-PG-HIGHSPEED-001C dedicated player-presence storage helpers.

PostgreSQL authenticated presence is owned by ``player_presence``. During the
reader cutover we keep ``players.last_seen`` as a low-frequency compatibility
mirror (<= once per four minutes), isolated by the caller with a SAVEPOINT.
That preserves legacy online/inactive readers while removing the former
per-presence-interval write pressure from the hot gameplay row.

SQLite keeps the established ``players.last_seen`` path.
"""

from __future__ import annotations

from typing import Dict, Iterable, Sequence

from .db import get_db_backend

PRESENCE_TABLE = "player_presence"
LEGACY_SYNC_INTERVAL_SEC = 4 * 60


def uses_dedicated_presence(*, backend: str | None = None) -> bool:
    return str(backend or get_db_backend()) == "postgres"


def last_seen_join_sql(
    *,
    player_alias: str = "p",
    presence_alias: str = "pp",
    backend: str | None = None,
) -> str:
    """JOIN clause required by effective_last_seen_sql on PostgreSQL."""
    if not uses_dedicated_presence(backend=backend):
        return ""
    return (
        f"LEFT JOIN {PRESENCE_TABLE} {presence_alias} "
        f"ON {presence_alias}.player_id = {player_alias}.id"
    )


def effective_last_seen_sql(
    *,
    player_alias: str = "p",
    presence_alias: str = "pp",
    backend: str | None = None,
) -> str:
    """Newest activity wins during rolling PostgreSQL presence cutover."""
    if uses_dedicated_presence(backend=backend):
        return (
            f"GREATEST(COALESCE({presence_alias}.last_seen, 0), "
            f"COALESCE({player_alias}.last_seen, 0))"
        )
    return f"COALESCE({player_alias}.last_seen, 0)"


def get_presence_last_seen(
    conn, player_id: int, *, backend: str | None = None
) -> int:  # noqa: ANN001
    """Read the hot presence timestamp without touching players on PostgreSQL."""
    pid = int(player_id)
    if uses_dedicated_presence(backend=backend):
        row = conn.execute(
            f"SELECT last_seen FROM {PRESENCE_TABLE} WHERE player_id = ? LIMIT 1;",
            (pid,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT last_seen FROM players WHERE id = ? LIMIT 1;",
            (pid,),
        ).fetchone()
    return int(row["last_seen"] or 0) if row else 0


def get_effective_last_seen(
    conn, player_id: int, *, backend: str | None = None
) -> int:  # noqa: ANN001
    """Read current activity for gameplay readers during the 001C cutover.

    PostgreSQL deliberately chooses the newer of dedicated presence and the
    temporary legacy mirror. This keeps rolling deployments correct when an old
    replica updates ``players.last_seen`` after a new replica created a
    ``player_presence`` row. Authenticated hot-touch code must continue using
    ``get_presence_last_seen`` instead.
    """
    pid = int(player_id)
    if uses_dedicated_presence(backend=backend):
        expr = effective_last_seen_sql(backend="postgres")
        join = last_seen_join_sql(backend="postgres")
        row = conn.execute(
            f"""
            SELECT {expr} AS last_seen
            FROM players p
            {join}
            WHERE p.id = ?
            LIMIT 1;
            """,
            (pid,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(last_seen, 0) AS last_seen FROM players WHERE id = ? LIMIT 1;",
            (pid,),
        ).fetchone()
    return int(row["last_seen"] or 0) if row else 0


def get_effective_last_seen_by_ids(
    conn,
    player_ids: Sequence[int] | Iterable[int],
    *,
    backend: str | None = None,
) -> Dict[int, int]:  # noqa: ANN001
    """Bulk effective activity read for ranking/galaxy/autoplay cutover."""
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    if uses_dedicated_presence(backend=backend):
        expr = effective_last_seen_sql(backend="postgres")
        join = last_seen_join_sql(backend="postgres")
        cur = conn.execute(
            f"""
            SELECT p.id AS player_id, {expr} AS last_seen
            FROM players p
            {join}
            WHERE p.id IN ({placeholders});
            """,
            tuple(ids),
        )
    else:
        cur = conn.execute(
            f"""
            SELECT id AS player_id, COALESCE(last_seen, 0) AS last_seen
            FROM players
            WHERE id IN ({placeholders});
            """,
            tuple(ids),
        )

    out = {pid: 0 for pid in ids}
    for row in cur.fetchall():
        out[int(row["player_id"])] = int(row["last_seen"] or 0)
    return out


def should_sync_legacy_last_seen(*, previous_seen: int, now: int) -> bool:
    """Keep legacy readers fresh without restoring the 30s players-row write."""
    return int(previous_seen or 0) <= int(now) - LEGACY_SYNC_INTERVAL_SEC


def sync_legacy_last_seen(conn, player_id: int, *, now: int) -> bool:  # noqa: ANN001
    """Best-effort PG mirror without ever waiting on the hot players row.

    ``players`` is gameplay state, not the canonical PostgreSQL presence owner.
    Acquire its row with ``SKIP LOCKED`` first; if gameplay currently owns the
    row, leave the compatibility timestamp stale for this request instead of
    burning the request lock timeout.
    """
    pid = int(player_id)
    row = conn.execute(
        "SELECT id FROM players WHERE id = ? FOR UPDATE SKIP LOCKED;",
        (pid,),
    ).fetchone()
    if not row:
        return False
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ? "
        "AND (last_seen IS NULL OR last_seen < ?);",
        (int(now), pid, int(now) - LEGACY_SYNC_INTERVAL_SEC),
    )
    return True


def touch_presence(
    conn,
    player_id: int,
    *,
    now: int,
    touch_before: int | None = None,
    backend: str | None = None,
) -> None:  # noqa: ANN001
    """Refresh one player presence using the backend-appropriate storage."""
    pid = int(player_id)
    ts = int(now)
    if uses_dedicated_presence(backend=backend):
        conn.execute(
            f"""
            INSERT INTO {PRESENCE_TABLE} (player_id, last_seen, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (player_id) DO UPDATE
            SET last_seen = excluded.last_seen,
                updated_at = excluded.updated_at
            WHERE {PRESENCE_TABLE}.last_seen < excluded.last_seen;
            """,
            (pid, ts, ts),
        )
        return

    before = int(touch_before if touch_before is not None else ts)
    conn.execute(
        "UPDATE players SET last_seen = ? "
        "WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
        (ts, pid, before),
    )


def touch_presence_bulk(
    conn,
    player_ids: Sequence[int] | Iterable[int],
    *,
    now: int,
    backend: str | None = None,
) -> None:  # noqa: ANN001
    """Refresh a tiny roster using the backend-appropriate presence storage."""
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return
    ts = int(now)
    if not uses_dedicated_presence(backend=backend):
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE players SET last_seen = ? WHERE id IN ({placeholders});",
            [ts, *ids],
        )
        return

    values = ",".join("(?, ?, ?)" for _ in ids)
    params: list[int] = []
    for pid in ids:
        params.extend((pid, ts, ts))
    conn.execute(
        f"""
        INSERT INTO {PRESENCE_TABLE} (player_id, last_seen, updated_at)
        VALUES {values}
        ON CONFLICT (player_id) DO UPDATE
        SET last_seen = excluded.last_seen,
            updated_at = excluded.updated_at
        WHERE {PRESENCE_TABLE}.last_seen < excluded.last_seen;
        """,
        params,
    )
