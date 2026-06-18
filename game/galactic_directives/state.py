"""Active galactic directive state — read-only resolver (GC-720C)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import begin_write_transaction, commit, db
from ..galaxy import get_galaxy_max
from .definitions import (
    get_directive_definition,
    normalize_directive_key,
    schema_ready,
)

FALLBACK_PRIMARY = "defensive"


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


def _default_state_row(galaxy: int) -> Dict[str, Any]:
    return {
        "galaxy": galaxy,
        "primary_directive": FALLBACK_PRIMARY,
        "secondary_directive": None,
        "primary_since": None,
        "consecutive_primary_wins": 0,
        "cooldown_directive": None,
        "cooldown_until_ym": None,
        "last_cycle_id": None,
        "updated_at": 0,
    }


def _fetch_state_row(galaxy: int, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM gd_galaxy_state WHERE galaxy = ? LIMIT 1;",
        (int(galaxy),),
    ).fetchone()
    return dict(row) if row else None


def ensure_galaxy_state(
    galaxy: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """
    Return ``gd_galaxy_state`` row for galaxy, inserting fallback defensive row if missing.

    Raises ``ValueError`` when galaxy is outside the playable range.
    """
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        raise ValueError("invalid_galaxy")

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return _default_state_row(galaxy_id)

        existing = _fetch_state_row(galaxy_id, conn)
        if existing is not None:
            return existing

        now = int(time.time())
        begin_write_transaction(conn)
        try:
            conn.execute(
                """
                INSERT INTO gd_galaxy_state (
                    galaxy, primary_directive, secondary_directive, primary_since,
                    consecutive_primary_wins, updated_at
                ) VALUES (?, ?, NULL, ?, 0, ?);
                """,
                (galaxy_id, FALLBACK_PRIMARY, now, now),
            )
            commit(conn)
        except sqlite3.Error:
            # Concurrent insert — fall through to read.
            pass

        row = _fetch_state_row(galaxy_id, conn)
        return row if row is not None else _default_state_row(galaxy_id)
    finally:
        if own_conn:
            conn.close()


def _resolve_active_keys(state: Dict[str, Any]) -> tuple[str, Optional[str], bool]:
    """Return (primary, secondary, used_read_fallback)."""
    raw_primary = state.get("primary_directive")
    primary = normalize_directive_key(raw_primary) or FALLBACK_PRIMARY
    used_fallback = bool(raw_primary) and normalize_directive_key(raw_primary) == ""

    raw_secondary = state.get("secondary_directive")
    secondary: Optional[str] = None
    if raw_secondary not in (None, ""):
        secondary = normalize_directive_key(raw_secondary) or None

    return primary, secondary, used_fallback


def _build_active_payload(
    galaxy_id: int,
    primary: str,
    secondary: Optional[str],
    *,
    source: str,
    conn: Optional[sqlite3.Connection],
) -> Dict[str, Any]:
    return {
        "galaxy": galaxy_id,
        "primary": primary,
        "secondary": secondary,
        "primary_definition": get_directive_definition(primary, conn=conn),
        "secondary_definition": (
            get_directive_definition(secondary, conn=conn) if secondary else None
        ),
        "source": source,
    }


def get_active_directives_for_galaxy(
    galaxy: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Active primary/secondary directives for one galaxy, or None if galaxy invalid."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        if not schema_ready(conn=conn):
            return _build_active_payload(
                galaxy_id,
                FALLBACK_PRIMARY,
                None,
                source="fallback",
                conn=conn,
            )

        had_row = _fetch_state_row(galaxy_id, conn) is not None
        state = ensure_galaxy_state(galaxy_id, conn=conn)
        primary, secondary, used_fallback = _resolve_active_keys(state)

        if not had_row or used_fallback:
            source = "fallback"
        else:
            source = "state"

        return _build_active_payload(
            galaxy_id,
            primary,
            secondary,
            source=source,
            conn=conn,
        )
    finally:
        if own_conn:
            conn.close()


def get_player_vote_galaxies(player_id: int, *, conn: sqlite3.Connection) -> List[int]:
    """Distinct galaxies where the player owns at least one colony."""
    if not schema_ready(conn=conn):
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT galaxy
        FROM planets
        WHERE player_id = ? AND galaxy IS NOT NULL
        ORDER BY galaxy ASC;
        """,
        (int(player_id),),
    ).fetchall()
    return [int(row["galaxy"]) for row in rows if row["galaxy"] is not None]


def count_pending_government_votes(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: Optional[int] = None,
) -> int:
    """
    Open directive vote cycles in the player's galaxies where they have not voted yet.
    Used by nav badges (GC-702) — server-only, no frontend time math.
    """
    if not schema_ready(conn=conn):
        return 0
    ts = int(now if now is not None else time.time())
    galaxies = get_player_vote_galaxies(player_id, conn=conn)
    if not galaxies:
        return 0
    placeholders = ",".join("?" * len(galaxies))
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM gd_cycles c
        WHERE c.galaxy IN ({placeholders})
          AND c.status = 'vote_open'
          AND c.vote_start_at <= ?
          AND c.vote_end_at >= ?
          AND NOT EXISTS (
            SELECT 1 FROM gd_votes v
            WHERE v.cycle_id = c.id AND v.player_id = ?
          );
        """,
        (*galaxies, ts, ts, int(player_id)),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def list_active_directives_for_galaxies(
    galaxies: List[Any],
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[int, Dict[str, Any]]:
    """Map galaxy id → active directive payload (invalid galaxies omitted)."""
    out: Dict[int, Dict[str, Any]] = {}
    own_conn = conn is None
    if own_conn:
        conn = db()
    try:
        for raw in galaxies:
            payload = get_active_directives_for_galaxy(raw, conn=conn)
            if payload is not None:
                out[int(payload["galaxy"])] = payload
        return out
    finally:
        if own_conn:
            conn.close()
