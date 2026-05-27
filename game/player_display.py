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
