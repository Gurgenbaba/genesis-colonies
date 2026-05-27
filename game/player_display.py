"""
Display helpers for player names (Commander title vs. actual name).
"""

from __future__ import annotations

import re

COMMANDER_PREFIX_RE = re.compile(r"^commander\s+", re.IGNORECASE)


def strip_commander_prefix(name: str | None) -> str:
    """Return the player name without a leading 'Commander ' prefix."""
    label = str(name or "").strip()
    if not label:
        return ""
    stripped = COMMANDER_PREFIX_RE.sub("", label, count=1).strip()
    return stripped or label


def commander_lookup_name(name: str | None) -> str:
    """Full stored name used for lookups (messages, chat, whisper)."""
    label = str(name or "").strip()
    return label or "Commander"


def commander_display_name(name: str | None) -> str:
    """Visible player name without the Commander prefix."""
    display = strip_commander_prefix(name)
    return display or commander_lookup_name(name)


def split_commander_name(name: str | None) -> dict[str, str]:
    lookup = commander_lookup_name(name)
    display = commander_display_name(name)
    return {
        "commander_lookup": lookup,
        "commander_display": display,
    }


def resolve_player_by_name(name: str | None, conn) -> tuple[dict | None, str | None]:
    """
    Look up a player by display or stored name (players table only).

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
    """Distinct name variants for DB lookups (exact match)."""
    q = str(name or "").strip()
    if not q:
        return []
    out: list[str] = []
    for candidate in (q, commander_lookup_name(q)):
        if candidate and candidate not in out:
            out.append(candidate)
    stripped = strip_commander_prefix(q)
    if stripped:
        prefixed = f"Commander {stripped}"
        for candidate in (stripped, prefixed):
            if candidate and candidate not in out:
                out.append(candidate)
    return out
