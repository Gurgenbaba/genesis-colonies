"""Launch cleanup for reserved Pirate AI accounts.

This module never guesses player identities. It only operates on the exact
reserved usernames declared in `PIRATE_BOT_USERNAMES`, and only while the
deployment-level Pirate AI kill switch is hard-off.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..db import table_exists
from ..ranking import recalculate_ranks
from .accounts import PIRATE_BOT_USERNAMES
from .settings import is_pirates_ai_hard_disabled


def _delete_where_player_ids(
    conn,
    table: str,
    column: str,
    player_ids: List[int],
) -> int:
    if not player_ids or not table_exists(conn, table):
        return 0
    placeholders = ",".join("?" for _ in player_ids)
    cur = conn.execute(
        f"DELETE FROM {table} WHERE {column} IN ({placeholders});",
        tuple(player_ids),
    )
    return max(0, int(cur.rowcount or 0))


def purge_reserved_pirate_accounts(*, conn) -> Dict[str, Any]:
    """Delete stale reserved Pirate AI accounts after a deployment hard-off.

    Caller owns the surrounding write transaction.
    """
    if not is_pirates_ai_hard_disabled():
        raise RuntimeError("pirate_ai_not_hard_disabled")

    usernames = sorted(str(name) for name in PIRATE_BOT_USERNAMES)
    if not usernames:
        return {"ok": True, "deleted": 0, "player_ids": [], "usernames": []}

    placeholders = ",".join("?" for _ in usernames)
    rows = conn.execute(
        f"""
        SELECT id, username
        FROM users
        WHERE username IN ({placeholders})
        ORDER BY id ASC;
        """,
        tuple(usernames),
    ).fetchall()

    player_ids = [int(row["id"]) for row in rows]
    found_usernames = [str(row["username"]) for row in rows]
    if not player_ids:
        return {
            "ok": True,
            "deleted": 0,
            "player_ids": [],
            "usernames": [],
            "ranking_rows_updated": 0,
        }

    planet_rows = conn.execute(
        f"""
        SELECT id
        FROM planets
        WHERE player_id IN ({",".join("?" for _ in player_ids)});
        """,
        tuple(player_ids),
    ).fetchall()
    planet_ids = [int(row["id"]) for row in planet_rows]

    cleanup_counts: Dict[str, int] = {}

    # Pirate tables intentionally created without FKs to players/planets.
    cleanup_counts["pirate_bot_state"] = _delete_where_player_ids(
        conn, "pirate_bot_state", "bot_player_id", player_ids
    )
    if table_exists(conn, "pirate_intel"):
        pid_ph = ",".join("?" for _ in player_ids)
        clauses = [
            f"bot_player_id IN ({pid_ph})",
            f"target_player_id IN ({pid_ph})",
        ]
        params: List[int] = [*player_ids, *player_ids]
        if planet_ids:
            planet_ph = ",".join("?" for _ in planet_ids)
            clauses.append(f"target_planet_id IN ({planet_ph})")
            params.extend(planet_ids)
        cur = conn.execute(
            "DELETE FROM pirate_intel WHERE " + " OR ".join(clauses) + ";",
            tuple(params),
        )
        cleanup_counts["pirate_intel"] = max(0, int(cur.rowcount or 0))

    if table_exists(conn, "pirate_action_log"):
        pid_ph = ",".join("?" for _ in player_ids)
        cur = conn.execute(
            f"""
            DELETE FROM pirate_action_log
            WHERE bot_player_id IN ({pid_ph})
               OR target_player_id IN ({pid_ph});
            """,
            tuple(player_ids) + tuple(player_ids),
        )
        cleanup_counts["pirate_action_log"] = max(0, int(cur.rowcount or 0))

    # The account owner handles normal user -> player -> planet cascades and
    # pre-cleans known non-cascading gameplay blockers.
    from ..options import hard_delete_player_account

    deleted: List[Dict[str, Any]] = []
    for player_id in player_ids:
        deleted.append(hard_delete_player_account(player_id, conn=conn))

    ranking_rows_updated = recalculate_ranks(conn=conn)

    return {
        "ok": True,
        "deleted": len(deleted),
        "player_ids": player_ids,
        "usernames": found_usernames,
        "planet_ids": planet_ids,
        "pirate_rows_deleted": cleanup_counts,
        "ranking_rows_updated": int(ranking_rows_updated or 0),
    }
