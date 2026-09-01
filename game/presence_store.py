"""GC-PG-HIGHSPEED-001C dedicated player-presence storage helpers.

PostgreSQL authenticated presence must not UPDATE or lock the hot ``players``
gameplay row. SQLite keeps the established ``players.last_seen`` path for
backward-compatible local/test behaviour; PostgreSQL uses ``player_presence``.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .db import get_db_backend

PRESENCE_TABLE = "player_presence"


def uses_dedicated_presence() -> bool:
    return get_db_backend() == "postgres"


def last_seen_join_sql(*, player_alias: str = "p", presence_alias: str = "pp") -> str:
    """JOIN clause required by effective_last_seen_sql on PostgreSQL."""
    if not uses_dedicated_presence():
        return ""
    return (
        f"LEFT JOIN {PRESENCE_TABLE} {presence_alias} "
        f"ON {presence_alias}.player_id = {player_alias}.id"
    )


def effective_last_seen_sql(*, player_alias: str = "p", presence_alias: str = "pp") -> str:
    """Read dedicated presence first, preserving legacy backfill fallback."""
    if uses_dedicated_presence():
        return f"COALESCE({presence_alias}.last_seen, {player_alias}.last_seen, 0)"
    return f"COALESCE({player_alias}.last_seen, 0)"


def get_presence_last_seen(conn, player_id: int) -> int:  # noqa: ANN001
    """Read the hot presence timestamp without touching players on PostgreSQL."""
    pid = int(player_id)
    if uses_dedicated_presence():
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


def touch_presence(conn, player_id: int, *, now: int, touch_before: int | None = None) -> None:  # noqa: ANN001
    """Refresh one player presence using the backend-appropriate storage."""
    pid = int(player_id)
    ts = int(now)
    if uses_dedicated_presence():
        # No FK by design: this UPSERT has no reason to lock players.
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


def touch_presence_bulk(conn, player_ids: Sequence[int] | Iterable[int], *, now: int) -> None:  # noqa: ANN001
    """Refresh a tiny roster without moving PostgreSQL locks onto players."""
    ids = sorted({int(pid) for pid in player_ids if int(pid) > 0})
    if not ids:
        return
    ts = int(now)
    if not uses_dedicated_presence():
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
