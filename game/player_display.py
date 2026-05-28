"""
Display helpers for player names (Commander title vs. actual name).

The word "Commander" in the UI is a label only (e.g. header tag). Player names
are always the raw value stored in the database.
"""

from __future__ import annotations


def commander_lookup_name(name: str | None) -> str:
    """Stored player name for lookups (messages, chat, whisper)."""
    label = str(name or "").strip()
    return label or "—"


def commander_display_name(name: str | None) -> str:
    """Visible player name – always the stored value."""
    return commander_lookup_name(name)


def split_commander_name(name: str | None) -> dict[str, str]:
    lookup = commander_lookup_name(name)
    display = commander_display_name(name)
    return {
        "commander_lookup": lookup,
        "commander_display": display,
    }


def resolve_player_by_name(name: str | None, conn) -> tuple[dict | None, str | None]:
    """
    Look up a player by exact stored name (players table only).

    Returns (player_row, error_key). error_key: validation, not_found, ambiguous.
    """
    q = str(name or "").strip()
    if len(q) < 2:
        return None, "validation"

    cur = conn.cursor()
    matches: dict[int, dict] = {}

    for candidate in commander_name_candidates(q):
        if len(candidate) < 2:
            continue
        cur.execute(
            """
            SELECT id, name FROM players
            WHERE LOWER(name) = LOWER(?)
            ORDER BY id ASC;
            """,
            (candidate,),
        )
        for row in cur.fetchall():
            pid = int(row["id"])
            matches[pid] = {"id": pid, "name": str(row["name"] or "")}

    if not matches:
        return None, "not_found"
    if len(matches) > 1:
        return None, "ambiguous"
    return next(iter(matches.values())), None


def commander_name_candidates(name: str | None) -> list[str]:
    """Distinct name variants for DB lookups (exact match only)."""
    q = str(name or "").strip()
    if not q:
        return []
    return [q]
