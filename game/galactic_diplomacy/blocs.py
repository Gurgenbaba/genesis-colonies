"""Alliance bloc assignment per galaxy (GC-721C)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import begin_write_transaction, commit, db
from ..galaxy import get_galaxy_max
from .definitions import get_bloc_definition, normalize_bloc_key, schema_ready


def normalize_galaxy(value: Any, *, conn: Optional[sqlite3.Connection] = None) -> Optional[int]:
    """Return playable galaxy id or None if out of range / invalid."""
    try:
        galaxy = int(value)
    except (TypeError, ValueError):
        return None
    if galaxy < 1:
        return None
    if galaxy > get_galaxy_max(conn):
        return None
    return galaxy


def _validate_alliance_id(alliance_id: Any) -> int:
    try:
        aid = int(alliance_id)
    except (TypeError, ValueError):
        raise ValueError("invalid_alliance_id")
    if aid <= 0:
        raise ValueError("invalid_alliance_id")
    return aid


def _build_bloc_payload(
    row: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    bloc_key = str(row.get("bloc_key") or "")
    definition = get_bloc_definition(bloc_key, conn=conn)
    return {
        "alliance_id": int(row["alliance_id"]),
        "galaxy": int(row["galaxy"]),
        "bloc_key": bloc_key,
        "definition": dict(definition) if definition else None,
        "since_at": int(row.get("since_at") or 0),
        "updated_at": int(row.get("updated_at") or 0),
    }


def set_alliance_bloc(
    alliance_id: Any,
    galaxy: Any,
    bloc_key: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Upsert alliance bloc for one galaxy. Raises ValueError on invalid input."""
    aid = _validate_alliance_id(alliance_id)
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    key = normalize_bloc_key(bloc_key)
    if not key:
        raise ValueError("invalid_bloc_key")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            raise ValueError("schema_not_ready")

        definition = get_bloc_definition(key, conn=conn)
        if not definition:
            raise ValueError("invalid_bloc_key")

        now = int(time.time())
        begin_write_transaction(conn)
        try:
            conn.execute(
                """
                INSERT INTO gd_alliance_blocs (
                    alliance_id, galaxy, bloc_key, since_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(alliance_id, galaxy) DO UPDATE SET
                    bloc_key = excluded.bloc_key,
                    updated_at = excluded.updated_at;
                """,
                (aid, galaxy_id, key, now, now),
            )
            commit(conn)
        except sqlite3.Error:
            raise

        row = conn.execute(
            """
            SELECT alliance_id, galaxy, bloc_key, since_at, updated_at
            FROM gd_alliance_blocs
            WHERE alliance_id = ? AND galaxy = ?
            LIMIT 1;
            """,
            (aid, galaxy_id),
        ).fetchone()
        if not row:
            raise RuntimeError("alliance_bloc_upsert_failed")
        return _build_bloc_payload(dict(row), conn=conn)
    finally:
        if own_conn:
            conn.close()


def get_alliance_bloc(
    alliance_id: Any,
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Return bloc assignment for alliance in galaxy, or None if unset / invalid galaxy."""
    try:
        aid = _validate_alliance_id(alliance_id)
    except ValueError:
        return None

    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return None

        row = conn.execute(
            """
            SELECT alliance_id, galaxy, bloc_key, since_at, updated_at
            FROM gd_alliance_blocs
            WHERE alliance_id = ? AND galaxy = ?
            LIMIT 1;
            """,
            (aid, galaxy_id),
        ).fetchone()
        if not row:
            return None
        return _build_bloc_payload(dict(row), conn=conn)
    finally:
        if own_conn:
            conn.close()


def list_alliance_blocs_for_galaxy(
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """All alliance bloc rows in a galaxy, sorted by alliance_id."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return []

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return []

        rows = conn.execute(
            """
            SELECT alliance_id, galaxy, bloc_key, since_at, updated_at
            FROM gd_alliance_blocs
            WHERE galaxy = ?
            ORDER BY alliance_id ASC;
            """,
            (galaxy_id,),
        ).fetchall()
        return [_build_bloc_payload(dict(row), conn=conn) for row in rows]
    finally:
        if own_conn:
            conn.close()


def clear_alliance_bloc(
    alliance_id: Any,
    galaxy: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> bool:
    """Remove bloc assignment. Returns True if a row was deleted."""
    try:
        aid = _validate_alliance_id(alliance_id)
    except ValueError:
        return False

    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return False

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return False

        begin_write_transaction(conn)
        try:
            cur = conn.execute(
                """
                DELETE FROM gd_alliance_blocs
                WHERE alliance_id = ? AND galaxy = ?;
                """,
                (aid, galaxy_id),
            )
            commit(conn)
            return int(cur.rowcount or 0) > 0
        except sqlite3.Error:
            raise
    finally:
        if own_conn:
            conn.close()
