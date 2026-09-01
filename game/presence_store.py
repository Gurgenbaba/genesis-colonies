"""GC-PG-HIGHSPEED-001C dedicated player-presence storage helpers.

PostgreSQL authenticated presence is owned exclusively by ``player_presence``.
All PostgreSQL activity readers use that canonical table; ``players.last_seen``
remains a SQLite compatibility column only.

SQLite keeps the established ``players.last_seen`` path.
"""

from __future__ import annotations

from typing import Dict, Iterable, Sequence

from .db import get_db_backend

PRESENCE_TABLE = "player_presence"

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
    """Backend-aware activity expression; PostgreSQL is canonical-only."""
    if uses_dedicated_presence(backend=backend):
        return f"COALESCE({presence_alias}.last_seen, 0)"
    return f"COALESCE({player_alias}.last_seen, 0)"


def effective_last_seen_scalar_sql(
    *,
    player_alias: str = "p",
    backend: str | None = None,
) -> str:
    """Correlated activity expression for existing player queries.

    PostgreSQL reads only canonical ``player_presence``. SQLite intentionally
    keeps the legacy players column for local/test compatibility.
    """
    if uses_dedicated_presence(backend=backend):
        return (
            f"COALESCE((SELECT pp_gc_presence.last_seen FROM {PRESENCE_TABLE} pp_gc_presence "
            f"WHERE pp_gc_presence.player_id = {player_alias}.id), 0)"
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
    """Read current activity from the backend's canonical presence owner."""
    pid = int(player_id)
    if uses_dedicated_presence(backend=backend):
        row = conn.execute(
            f"SELECT last_seen FROM {PRESENCE_TABLE} WHERE player_id = ? LIMIT 1;",
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
    """Bulk activity read from the backend's canonical presence owner."""
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    if uses_dedicated_presence(backend=backend):
        cur = conn.execute(
            f"""
            SELECT player_id, COALESCE(last_seen, 0) AS last_seen
            FROM {PRESENCE_TABLE}
            WHERE player_id IN ({placeholders});
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
