"""Galactic directive voting cycles — monthly galaxy-scoped elections (GC-720G)."""

from __future__ import annotations

import calendar
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..db import begin_write_transaction, commit, db
from .definitions import (
    get_directive_definition,
    list_directive_definitions,
    normalize_directive_key,
    schema_ready,
)
from .state import (
    FALLBACK_PRIMARY,
    ensure_galaxy_state,
    get_active_directives_for_galaxy,
    get_player_vote_galaxies,
    normalize_galaxy,
)

PHASE_VOTE_OPEN = "vote_open"
PHASE_ACTIVE = "active"
PHASE_RESOLVED = "resolved"


def _utc_ts(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc).timestamp())


def _calendar_parts(ts: int) -> Tuple[int, int]:
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return int(dt.year), int(dt.month)


def _next_month(year: int, month: int) -> Tuple[int, int]:
    if month >= 12:
        return year + 1, 1
    return year, month + 1


def _ym_key(year: int, month: int) -> str:
    return f"{int(year):04d}{int(month):02d}"


def _cycle_timestamps(year: int, month: int) -> Dict[str, int]:
    last_day = calendar.monthrange(int(year), int(month))[1]
    return {
        "vote_start_at": _utc_ts(year, month, 1, 0, 0, 0),
        "vote_end_at": _utc_ts(year, month, 5, 23, 59, 59),
        "effect_start_at": _utc_ts(year, month, 6, 0, 0, 0),
        "effect_end_at": _utc_ts(year, month, last_day, 23, 59, 59),
    }


def _row_to_cycle(row: sqlite3.Row | Dict[str, Any]) -> Dict[str, Any]:
    return dict(row) if not isinstance(row, dict) else dict(row)


def get_vote_phase(cycle: Dict[str, Any], now: Optional[int] = None) -> str:
    """Return vote_open, active, or resolved for a cycle row."""
    ts = int(now if now is not None else time.time())
    vote_end = int(cycle.get("vote_end_at") or 0)
    effect_end = int(cycle.get("effect_end_at") or 0)
    if ts <= vote_end:
        return PHASE_VOTE_OPEN
    if ts <= effect_end:
        return PHASE_ACTIVE
    return PHASE_RESOLVED


def _fetch_cycle(galaxy: int, year: int, month: int, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ? AND year = ? AND month = ?
        LIMIT 1;
        """,
        (int(galaxy), int(year), int(month)),
    ).fetchone()
    return _row_to_cycle(row) if row else None


def _sync_cycle_status(cycle: Dict[str, Any], *, conn: sqlite3.Connection, now: int) -> Dict[str, Any]:
    phase = get_vote_phase(cycle, now)
    stored = str(cycle.get("status") or "")
    if stored == phase:
        return cycle
    conn.execute(
        "UPDATE gd_cycles SET status = ?, updated_at = ? WHERE id = ?;",
        (phase, now, int(cycle["id"])),
    )
    commit(conn)
    cycle = dict(cycle)
    cycle["status"] = phase
    cycle["updated_at"] = now
    return cycle


def _resolve_overdue_cycles(galaxy_id: int, *, conn: sqlite3.Connection, now: int) -> None:
    rows = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE galaxy = ?
          AND (
            (status != ? AND effect_end_at < ?)
            OR (status = ? AND vote_end_at < ? AND winning_primary IS NULL)
            OR (status = ? AND vote_end_at < ? AND effect_end_at >= ?)
          )
        ORDER BY year ASC, month ASC;
        """,
        (
            int(galaxy_id),
            PHASE_RESOLVED,
            now,
            PHASE_VOTE_OPEN,
            now,
            PHASE_VOTE_OPEN,
            now,
            now,
        ),
    ).fetchall()
    for row in rows:
        cycle = _row_to_cycle(row)
        if int(cycle.get("vote_end_at") or 0) < now and not cycle.get("winning_primary"):
            resolve_directive_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn=conn, now=now)
            cycle = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn) or cycle
        if get_vote_phase(cycle, now) == PHASE_RESOLVED and str(cycle.get("status")) != PHASE_RESOLVED:
            _sync_cycle_status(cycle, conn=conn, now=now)


def get_or_create_current_cycle(
    galaxy: Any,
    now: Optional[int] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Return the current calendar-month cycle for a galaxy, creating it if needed."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return None

        _resolve_overdue_cycles(galaxy_id, conn=conn, now=ts)
        year, month = _calendar_parts(ts)
        cycle = _fetch_cycle(galaxy_id, year, month, conn)
        if cycle is None:
            stamps = _cycle_timestamps(year, month)
            phase = get_vote_phase({**stamps}, ts)
            begin_write_transaction(conn)
            try:
                conn.execute(
                    """
                    INSERT INTO gd_cycles (
                        galaxy, year, month,
                        vote_start_at, vote_end_at, effect_start_at, effect_end_at,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        galaxy_id,
                        year,
                        month,
                        stamps["vote_start_at"],
                        stamps["vote_end_at"],
                        stamps["effect_start_at"],
                        stamps["effect_end_at"],
                        phase,
                        ts,
                        ts,
                    ),
                )
                commit(conn)
            except sqlite3.IntegrityError:
                pass
            cycle = _fetch_cycle(galaxy_id, year, month, conn)

        if cycle is None:
            return None

        if int(cycle.get("vote_end_at") or 0) < ts and not cycle.get("winning_primary"):
            resolve_directive_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn=conn, now=ts)
            cycle = _fetch_cycle(galaxy_id, int(cycle["year"]), int(cycle["month"]), conn) or cycle

        return _sync_cycle_status(cycle, conn=conn, now=ts)
    finally:
        if own_conn:
            conn.close()


def _tally_votes(cycle_id: int, conn: sqlite3.Connection) -> List[Tuple[str, int]]:
    rows = conn.execute(
        """
        SELECT directive_key, COUNT(*) AS vote_count
        FROM gd_votes
        WHERE cycle_id = ?
        GROUP BY directive_key
        ORDER BY vote_count DESC, directive_key ASC;
        """,
        (int(cycle_id),),
    ).fetchall()
    out: List[Tuple[str, int]] = []
    for row in rows:
        key = normalize_directive_key(row["directive_key"])
        if not key:
            continue
        out.append((key, int(row["vote_count"] or 0)))
    return out


def _pick_from_tied(candidates: List[str]) -> str:
    if not candidates:
        return FALLBACK_PRIMARY
    return random.choice(candidates)


def _resolve_winners(
    tallies: List[Tuple[str, int]],
) -> Tuple[str, Optional[str], int, int, bool, bool]:
    if not tallies:
        return "", None, 0, 0, False, False

    top_votes = tallies[0][1]
    primary_candidates = [key for key, count in tallies if count == top_votes]
    primary = _pick_from_tied(primary_candidates)
    tie_primary = len(primary_candidates) > 1

    remaining = [(key, count) for key, count in tallies if key != primary]
    secondary: Optional[str] = None
    secondary_votes = 0
    tie_secondary = False
    if remaining:
        second_votes = remaining[0][1]
        secondary_candidates = [key for key, count in remaining if count == second_votes]
        secondary = _pick_from_tied(secondary_candidates)
        secondary_votes = second_votes
        tie_secondary = len(secondary_candidates) > 1

    return primary, secondary, top_votes, secondary_votes, tie_primary, tie_secondary


def _directive_on_cooldown(
    state: Dict[str, Any],
    directive_key: str,
    year: int,
    month: int,
) -> bool:
    cd_key = normalize_directive_key(state.get("cooldown_directive"))
    until = str(state.get("cooldown_until_ym") or "").strip()
    if not cd_key or not until:
        return False
    return cd_key == directive_key and until == _ym_key(year, month)


def resolve_directive_cycle(
    galaxy: Any,
    year: int,
    month: int,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Tally votes for a cycle and write winners into gd_galaxy_state."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    if galaxy_id is None:
        return None

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return None

        cycle = _fetch_cycle(galaxy_id, int(year), int(month), conn)
        if cycle is None:
            return None

        if int(cycle.get("vote_end_at") or 0) > ts:
            return cycle

        if cycle.get("winning_primary"):
            return _sync_cycle_status(cycle, conn=conn, now=ts)

        state = ensure_galaxy_state(galaxy_id, conn=conn)
        tallies = _tally_votes(int(cycle["id"]), conn)
        total_votes = sum(count for _, count in tallies)
        total_voters = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM gd_votes WHERE cycle_id = ?;",
                (int(cycle["id"]),),
            ).fetchone()["c"]
            or 0
        )

        tie_p = False
        tie_s = False
        if tallies:
            primary, secondary, p_votes, s_votes, tie_p, tie_s = _resolve_winners(tallies)
        else:
            primary = normalize_directive_key(state.get("primary_directive")) or FALLBACK_PRIMARY
            raw_secondary = state.get("secondary_directive")
            secondary = (
                normalize_directive_key(raw_secondary) or None
                if raw_secondary not in (None, "")
                else None
            )
            p_votes = 0
            s_votes = 0

        old_primary = normalize_directive_key(state.get("primary_directive")) or FALLBACK_PRIMARY
        consecutive = int(state.get("consecutive_primary_wins") or 0)
        if primary == old_primary:
            consecutive += 1
        else:
            consecutive = 1 if primary else 0

        cooldown_directive = state.get("cooldown_directive")
        cooldown_until_ym = state.get("cooldown_until_ym")
        if primary and consecutive >= 2:
            next_year, next_month = _next_month(int(year), int(month))
            cooldown_directive = primary
            cooldown_until_ym = _ym_key(next_year, next_month)
            consecutive = 0

        phase = get_vote_phase(cycle, ts)
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE gd_cycles
            SET winning_primary = ?,
                winning_secondary = ?,
                winning_primary_votes = ?,
                winning_secondary_votes = ?,
                total_votes = ?,
                total_voters = ?,
                is_tie_primary = ?,
                is_tie_secondary = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?;
            """,
            (
                primary or None,
                secondary,
                int(p_votes),
                int(s_votes),
                int(total_votes),
                int(total_voters),
                1 if tie_p else 0,
                1 if tie_s else 0,
                phase,
                ts,
                int(cycle["id"]),
            ),
        )
        conn.execute(
            """
            UPDATE gd_galaxy_state
            SET primary_directive = ?,
                secondary_directive = ?,
                primary_since = CASE WHEN ? IS NOT NULL THEN ? ELSE primary_since END,
                consecutive_primary_wins = ?,
                cooldown_directive = ?,
                cooldown_until_ym = ?,
                last_cycle_id = ?,
                updated_at = ?
            WHERE galaxy = ?;
            """,
            (
                primary or FALLBACK_PRIMARY,
                secondary,
                primary,
                ts,
                int(consecutive),
                cooldown_directive,
                cooldown_until_ym,
                int(cycle["id"]),
                ts,
                galaxy_id,
            ),
        )
        commit(conn)
        return _fetch_cycle(galaxy_id, int(year), int(month), conn)
    finally:
        if own_conn:
            conn.close()


def _player_has_vote_right(player_id: int, galaxy_id: int, conn: sqlite3.Connection) -> bool:
    return galaxy_id in get_player_vote_galaxies(int(player_id), conn=conn)


def submit_directive_vote(
    player_id: int,
    galaxy: Any,
    directive_key: str,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """Cast or update a player's vote for the current cycle in a galaxy."""
    galaxy_id = normalize_galaxy(galaxy, conn=conn)
    key = normalize_directive_key(directive_key)
    if galaxy_id is None:
        return {"ok": False, "reason": "invalid_galaxy"}
    if not key:
        return {"ok": False, "reason": "invalid_directive"}

    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready"}

        if not _player_has_vote_right(int(player_id), galaxy_id, conn):
            return {"ok": False, "reason": "no_colony"}

        cycle = get_or_create_current_cycle(galaxy_id, now=ts, conn=conn)
        if cycle is None:
            return {"ok": False, "reason": "cycle_unavailable"}

        phase = get_vote_phase(cycle, ts)
        if phase != PHASE_VOTE_OPEN:
            return {"ok": False, "reason": "vote_closed"}

        state = ensure_galaxy_state(galaxy_id, conn=conn)
        if _directive_on_cooldown(state, key, int(cycle["year"]), int(cycle["month"])):
            return {"ok": False, "reason": "cooldown"}

        definition = get_directive_definition(key, conn=conn)
        if definition is None:
            return {"ok": False, "reason": "invalid_directive"}

        eligible = definition.get("eligible_as") or []
        if isinstance(eligible, str):
            eligible = []
        if "primary" not in eligible:
            return {"ok": False, "reason": "invalid_directive"}

        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO gd_votes (cycle_id, galaxy, player_id, directive_key, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cycle_id, player_id) DO UPDATE SET
                directive_key = excluded.directive_key,
                updated_at = excluded.updated_at;
            """,
            (int(cycle["id"]), galaxy_id, int(player_id), key, ts, ts),
        )
        commit(conn)
        return {"ok": True, "directive": key, "galaxy": galaxy_id, "cycle_id": int(cycle["id"])}
    finally:
        if own_conn:
            conn.close()


def _phase_countdown_seconds(cycle: Dict[str, Any], phase: str, now: int) -> int:
    if phase == PHASE_VOTE_OPEN:
        return max(0, int(cycle.get("vote_end_at") or 0) - now)
    if phase == PHASE_ACTIVE:
        return max(0, int(cycle.get("effect_end_at") or 0) - now)
    return 0


def _vote_tallies_for_cycle(cycle_id: int, conn: sqlite3.Connection) -> Dict[str, int]:
    rows = conn.execute(
        """
        SELECT directive_key, COUNT(*) AS vote_count
        FROM gd_votes
        WHERE cycle_id = ?
        GROUP BY directive_key;
        """,
        (int(cycle_id),),
    ).fetchall()
    out: Dict[str, int] = {}
    for row in rows:
        key = normalize_directive_key(row["directive_key"])
        if key:
            out[key] = int(row["vote_count"] or 0)
    return out


def _serialize_directive_option(
    definition: Dict[str, Any],
    *,
    vote_count: int,
    selected: bool,
    on_cooldown: bool,
) -> Dict[str, Any]:
    key = str(definition.get("directive_key") or "")
    return {
        "key": key,
        "label_key": str(definition.get("label_key") or f"gd_dir_{key}_title"),
        "description_key": str(definition.get("description_key") or f"gd_dir_{key}_desc"),
        "vote_count": int(vote_count),
        "selected": bool(selected),
        "on_cooldown": bool(on_cooldown),
    }


def build_galaxy_politics_entry(
    player_id: int,
    galaxy_id: int,
    *,
    conn: sqlite3.Connection,
    now: int,
) -> Dict[str, Any]:
    cycle = get_or_create_current_cycle(galaxy_id, now=now, conn=conn)
    active = get_active_directives_for_galaxy(galaxy_id, conn=conn) or {}
    state = ensure_galaxy_state(galaxy_id, conn=conn)
    phase = get_vote_phase(cycle, now) if cycle else PHASE_RESOLVED
    has_right = _player_has_vote_right(player_id, galaxy_id, conn)

    player_vote: Optional[str] = None
    if cycle:
        row = conn.execute(
            """
            SELECT directive_key FROM gd_votes
            WHERE cycle_id = ? AND player_id = ?
            LIMIT 1;
            """,
            (int(cycle["id"]), int(player_id)),
        ).fetchone()
        if row:
            player_vote = normalize_directive_key(row["directive_key"]) or None

    tallies = _vote_tallies_for_cycle(int(cycle["id"]), conn) if cycle else {}
    options: List[Dict[str, Any]] = []
    for definition in list_directive_definitions(conn=conn):
        key = str(definition.get("directive_key") or "")
        eligible = definition.get("eligible_as") or []
        if isinstance(eligible, str) or "primary" not in eligible:
            continue
        options.append(
            _serialize_directive_option(
                definition,
                vote_count=int(tallies.get(key, 0)),
                selected=player_vote == key,
                on_cooldown=_directive_on_cooldown(
                    state,
                    key,
                    int(cycle["year"]) if cycle else 0,
                    int(cycle["month"]) if cycle else 0,
                ),
            )
        )

    can_vote = bool(has_right and cycle and phase == PHASE_VOTE_OPEN)
    vote_reason: Optional[str] = None
    if not has_right:
        vote_reason = "no_colony"
    elif phase != PHASE_VOTE_OPEN:
        vote_reason = "vote_closed"

    return {
        "galaxy": galaxy_id,
        "active": {
            "primary": active.get("primary"),
            "secondary": active.get("secondary"),
            "primary_label_key": (active.get("primary_definition") or {}).get("label_key"),
            "secondary_label_key": (active.get("secondary_definition") or {}).get("label_key"),
        },
        "cycle": {
            "id": int(cycle["id"]) if cycle else None,
            "year": int(cycle["year"]) if cycle else None,
            "month": int(cycle["month"]) if cycle else None,
            "phase": phase,
            "status": str(cycle.get("status") or phase) if cycle else PHASE_RESOLVED,
            "vote_end_at": int(cycle.get("vote_end_at") or 0) if cycle else 0,
            "effect_end_at": int(cycle.get("effect_end_at") or 0) if cycle else 0,
            "countdown_seconds": _phase_countdown_seconds(cycle, phase, now) if cycle else 0,
        },
        "player_vote": player_vote,
        "can_vote": can_vote,
        "vote_reason": vote_reason,
        "options": options,
    }


def get_galactic_politics_state(
    player_id: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """UI payload for /galactic-politics."""
    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ready": False, "galaxies": [], "server_time": ts}

        galaxies = get_player_vote_galaxies(int(player_id), conn=conn)
        entries = [
            build_galaxy_politics_entry(int(player_id), galaxy_id, conn=conn, now=ts)
            for galaxy_id in galaxies
        ]
        return {"ready": True, "galaxies": entries, "server_time": ts}
    finally:
        if own_conn:
            conn.close()
