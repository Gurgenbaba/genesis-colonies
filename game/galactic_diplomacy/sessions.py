"""Diplomatic resolution vote sessions — player JA/NEIN (GC-POL-05)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import begin_write_transaction, commit, db, table_exists
from ..galactic_directives.state import get_player_vote_galaxies
from .blocs import normalize_galaxy
from .definitions import schema_ready
from .emergencies import set_active_emergency
from .resolutions import (
    get_resolution_definition,
    normalize_resolution_key,
    resolution_schema_ready,
    set_active_resolution,
)

SESSION_VOTE_OPEN = "vote_open"
SESSION_PASSED = "passed"
SESSION_FAILED = "failed"
SESSION_EXPIRED = "expired"
QUORUM_PCT = 0.15
DEFAULT_VOTE_HOURS = 72
BLOC_COOLDOWN_SECONDS = 30 * 86400


def sessions_schema_ready(*, conn: sqlite3.Connection) -> bool:
    try:
        return table_exists(conn, "gd_resolution_sessions") and table_exists(
            conn, "gd_resolution_session_votes"
        )
    except Exception:
        return False


def _eligible_voters(galaxy_id: int, conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT player_id) AS c
        FROM planets
        WHERE galaxy = ? AND player_id IS NOT NULL;
        """,
        (int(galaxy_id),),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def _quorum_needed(eligible: int) -> int:
    return max(1, int(eligible * QUORUM_PCT + 0.999)) if eligible > 0 else 1


def _serialize_session(
    row: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    player_id: Optional[int] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    key = normalize_resolution_key(row.get("resolution_key"))
    definition = get_resolution_definition(key, conn=conn) if key else None
    ts = int(now if now is not None else time.time())
    vote_end = int(row.get("vote_end_at") or 0)
    status = str(row.get("status") or SESSION_VOTE_OPEN)
    player_choice = None
    if player_id and row.get("id") is not None:
        vote = conn.execute(
            """
            SELECT choice FROM gd_resolution_session_votes
            WHERE session_id = ? AND player_id = ?
            LIMIT 1;
            """,
            (int(row["id"]), int(player_id)),
        ).fetchone()
        if vote:
            player_choice = str(vote["choice"] or "")
    yes_votes = int(row.get("yes_votes") or 0)
    no_votes = int(row.get("no_votes") or 0)
    total = yes_votes + no_votes
    return {
        "id": int(row["id"]),
        "galaxy": int(row["galaxy"]),
        "resolution_key": key,
        "label_key": (definition or {}).get("label_key") or f"gdp_res_{key}_title",
        "description_key": (definition or {}).get("description_key") or f"gdp_res_{key}_desc",
        "status": status,
        "vote_start_at": int(row.get("vote_start_at") or 0),
        "vote_end_at": vote_end,
        "countdown_seconds": max(0, vote_end - ts) if status == SESSION_VOTE_OPEN else 0,
        "yes_votes": yes_votes,
        "no_votes": no_votes,
        "total_votes": total,
        "yes_share": round(100.0 * yes_votes / total, 1) if total else 0.0,
        "no_share": round(100.0 * no_votes / total, 1) if total else 0.0,
        "quorum_needed": int(row.get("quorum_needed") or 0),
        "total_eligible": int(row.get("total_eligible") or 0),
        "quorum_met": total >= int(row.get("quorum_needed") or 0),
        "result": row.get("result"),
        "player_choice": player_choice,
        "can_vote": bool(
            player_id
            and status == SESSION_VOTE_OPEN
            and ts <= vote_end
            and int(row["galaxy"]) in get_player_vote_galaxies(int(player_id), conn=conn)
        ),
    }


def get_open_resolution_session(
    galaxy: Any,
    *,
    conn: sqlite3.Connection,
    player_id: Optional[int] = None,
    now: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None or not sessions_schema_ready(conn=conn):
        return None
    ts = int(now if now is not None else time.time())
    _resolve_due_sessions_for_galaxy(galaxy_id, conn=conn, now=ts)
    row = conn.execute(
        """
        SELECT * FROM gd_resolution_sessions
        WHERE galaxy = ? AND status = ?
        ORDER BY id DESC
        LIMIT 1;
        """,
        (galaxy_id, SESSION_VOTE_OPEN),
    ).fetchone()
    if not row:
        return None
    return _serialize_session(dict(row), conn=conn, player_id=player_id, now=ts)


def open_resolution_session(
    galaxy: Any,
    resolution_key: str,
    *,
    created_by: Optional[int] = None,
    vote_hours: int = DEFAULT_VOTE_HOURS,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a JA/NEIN session. Fails if one is already open for the galaxy."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    key = normalize_resolution_key(resolution_key)
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}
    if not key:
        return {"ok": False, "reason": "invalid_resolution"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn) or not resolution_schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}
        if not sessions_schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}
        if not get_resolution_definition(key, conn=conn):
            return {"ok": False, "reason": "invalid_resolution"}

        existing = conn.execute(
            """
            SELECT id FROM gd_resolution_sessions
            WHERE galaxy = ? AND status = ?
            LIMIT 1;
            """,
            (galaxy_id, SESSION_VOTE_OPEN),
        ).fetchone()
        if existing:
            return {"ok": False, "reason": "session_open", "session_id": int(existing["id"])}

        eligible = _eligible_voters(galaxy_id, conn)
        quorum = _quorum_needed(eligible)
        hours = max(1, int(vote_hours or DEFAULT_VOTE_HOURS))
        vote_end = ts + hours * 3600
        begin_write_transaction(conn)
        cur = conn.execute(
            """
            INSERT INTO gd_resolution_sessions (
                galaxy, resolution_key, status, vote_start_at, vote_end_at,
                yes_votes, no_votes, quorum_needed, total_eligible,
                created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?, ?);
            """,
            (
                galaxy_id,
                key,
                SESSION_VOTE_OPEN,
                ts,
                vote_end,
                quorum,
                eligible,
                int(created_by) if created_by else None,
                ts,
                ts,
            ),
        )
        session_id = int(cur.lastrowid)
        commit(conn)
        row = conn.execute(
            "SELECT * FROM gd_resolution_sessions WHERE id = ?;", (session_id,)
        ).fetchone()
        return {
            "ok": True,
            "session": _serialize_session(dict(row), conn=conn, player_id=created_by, now=ts),
        }
    finally:
        if own_conn:
            conn.close()


def submit_resolution_vote(
    player_id: int,
    session_id: int,
    choice: str,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Cast or update yes/no on an open resolution session."""
    raw_choice = str(choice or "").strip().lower()
    if raw_choice not in ("yes", "no"):
        return {"ok": False, "reason": "invalid_choice"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not sessions_schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}

        row = conn.execute(
            "SELECT * FROM gd_resolution_sessions WHERE id = ? LIMIT 1;",
            (int(session_id),),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "not_found"}
        session = dict(row)
        if str(session.get("status")) != SESSION_VOTE_OPEN:
            return {"ok": False, "reason": "vote_closed"}
        if ts > int(session.get("vote_end_at") or 0):
            _resolve_session(session, conn=conn, now=ts)
            return {"ok": False, "reason": "vote_closed"}

        galaxy_id = int(session["galaxy"])
        if galaxy_id not in get_player_vote_galaxies(int(player_id), conn=conn):
            return {"ok": False, "reason": "no_colony"}

        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO gd_resolution_session_votes (
                session_id, player_id, choice, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, player_id) DO UPDATE SET
                choice = excluded.choice,
                updated_at = excluded.updated_at;
            """,
            (int(session_id), int(player_id), raw_choice, ts, ts),
        )
        tallies = conn.execute(
            """
            SELECT
                SUM(CASE WHEN choice = 'yes' THEN 1 ELSE 0 END) AS yes_votes,
                SUM(CASE WHEN choice = 'no' THEN 1 ELSE 0 END) AS no_votes
            FROM gd_resolution_session_votes
            WHERE session_id = ?;
            """,
            (int(session_id),),
        ).fetchone()
        yes_votes = int(tallies["yes_votes"] or 0) if tallies else 0
        no_votes = int(tallies["no_votes"] or 0) if tallies else 0
        conn.execute(
            """
            UPDATE gd_resolution_sessions
            SET yes_votes = ?, no_votes = ?, updated_at = ?
            WHERE id = ?;
            """,
            (yes_votes, no_votes, ts, int(session_id)),
        )
        commit(conn)
        refreshed = conn.execute(
            "SELECT * FROM gd_resolution_sessions WHERE id = ?;", (int(session_id),)
        ).fetchone()
        return {
            "ok": True,
            "choice": raw_choice,
            "session": _serialize_session(
                dict(refreshed), conn=conn, player_id=int(player_id), now=ts
            ),
        }
    finally:
        if own_conn:
            conn.close()


def _resolve_session(
    session: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Dict[str, Any]:
    if str(session.get("status")) != SESSION_VOTE_OPEN:
        return session
    yes_votes = int(session.get("yes_votes") or 0)
    no_votes = int(session.get("no_votes") or 0)
    total = yes_votes + no_votes
    quorum = int(session.get("quorum_needed") or 0)
    key = normalize_resolution_key(session.get("resolution_key"))

    if total < quorum:
        status, result = SESSION_EXPIRED, "failed"
    elif yes_votes > no_votes:
        status, result = SESSION_PASSED, "yes"
    else:
        status, result = SESSION_FAILED, "no"

    begin_write_transaction(conn)
    conn.execute(
        """
        UPDATE gd_resolution_sessions
        SET status = ?, result = ?, updated_at = ?
        WHERE id = ?;
        """,
        (status, result, int(now), int(session["id"])),
    )
    commit(conn)

    if status == SESSION_PASSED and key:
        try:
            set_active_resolution(int(session["galaxy"]), key, conn=conn)
        except (ValueError, RuntimeError):
            pass
        if key == "emergency_session":
            try:
                set_active_emergency(int(session["galaxy"]), "galaxy_war", conn=conn)
            except (ValueError, RuntimeError):
                pass

    session = dict(session)
    session["status"] = status
    session["result"] = result
    return session


def _resolve_due_sessions_for_galaxy(
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    now: int,
) -> None:
    if not sessions_schema_ready(conn=conn):
        return
    rows = conn.execute(
        """
        SELECT * FROM gd_resolution_sessions
        WHERE galaxy = ? AND status = ? AND vote_end_at < ?;
        """,
        (int(galaxy_id), SESSION_VOTE_OPEN, int(now)),
    ).fetchall()
    for row in rows:
        _resolve_session(dict(row), conn=conn, now=now)


def resolve_due_resolution_sessions(
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    resolved: List[int] = []
    try:
        if not sessions_schema_ready(conn=conn):
            return {"ok": True, "resolved": []}
        rows = conn.execute(
            """
            SELECT * FROM gd_resolution_sessions
            WHERE status = ? AND vote_end_at < ?;
            """,
            (SESSION_VOTE_OPEN, ts),
        ).fetchall()
        for row in rows:
            session = _resolve_session(dict(row), conn=conn, now=ts)
            resolved.append(int(session["id"]))
        return {"ok": True, "resolved": resolved}
    finally:
        if own_conn:
            conn.close()
