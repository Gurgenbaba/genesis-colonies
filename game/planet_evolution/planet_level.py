"""Planet XP and level progression."""

from __future__ import annotations

import math
import sqlite3
from typing import Any, Dict, Optional, Tuple

from .constants import LEVEL_UNLOCKS, MAX_PLANET_LEVEL
from .history import append_history
from .repository import get_legacy_tags, get_planet_row


def xp_threshold_for_level(level: int) -> int:
    """Cumulative XP required to reach `level` (level 1 => 0)."""
    lvl = max(1, int(level))
    if lvl <= 1:
        return 0
    return int(math.floor(100 * (lvl ** 1.55)))


def xp_for_level(level: int) -> int:
    """XP required to advance from `level` to `level + 1`."""
    lvl = max(1, int(level))
    if lvl >= MAX_PLANET_LEVEL:
        return 0
    return max(1, xp_threshold_for_level(lvl + 1) - xp_threshold_for_level(lvl))


def xp_to_next_level(planet_level: int, planet_xp: int) -> int:
    """Remaining XP until the next level."""
    lvl = max(1, int(planet_level))
    if lvl >= MAX_PLANET_LEVEL:
        return 0
    target = xp_threshold_for_level(lvl + 1)
    return max(0, target - int(planet_xp))


def _diversity_bonus(planet_id: int, conn: sqlite3.Connection) -> float:
    tags = get_legacy_tags(planet_id, conn=conn)
    return min(1.25, 1.0 + 0.05 * len(tags))


def _apply_level_unlocks(planet_id: int, new_level: int, conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    unlocks = LEVEL_UNLOCKS.get(int(new_level)) or ()
    reveal_delta = 0
    for item in unlocks:
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "dna_reveal":
            reveal_delta = max(reveal_delta, int(item[1]))
        elif item == "dna_reveal":
            reveal_delta = max(reveal_delta, 1)

    if reveal_delta > 0:
        cur.execute(
            """
            UPDATE planets
            SET dna_reveal_tier = MAX(dna_reveal_tier, ?)
            WHERE id = ?;
            """,
            (int(reveal_delta), int(planet_id)),
        )


def add_planet_xp(
    planet_id: int,
    base_xp: int,
    conn: sqlite3.Connection,
    *,
    reason: Optional[str] = None,
    skip_diversity: bool = False,
) -> Dict[str, Any]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    level = int(planet.get("planet_level") or 1)
    xp = int(planet.get("planet_xp") or 0)

    bonus = 1.0 if skip_diversity else _diversity_bonus(planet_id, conn)
    # GC-720J: expansion directive planet XP multiplier (optional level cap).
    try:
        from game.galactic_directives.mechanics import get_directive_flags_for_galaxy

        galaxy = int(planet.get("galaxy") or 0)
        if galaxy > 0:
            flags = get_directive_flags_for_galaxy(galaxy, conn=conn) or {}
            xp_mult = float(flags.get("planet_xp_mult") or 1.0)
            cap_level = int(flags.get("planet_xp_mult_cap_level") or 0)
            if xp_mult != 1.0 and (cap_level <= 0 or level < cap_level):
                bonus *= xp_mult
    except Exception:
        pass
    gained = max(0, int(math.floor(int(base_xp) * bonus)))
    xp += gained

    levels_gained = 0
    while level < MAX_PLANET_LEVEL and xp >= xp_threshold_for_level(level + 1):
        level += 1
        levels_gained += 1
        _apply_level_unlocks(planet_id, level, conn)
        append_history(
            planet_id,
            "level_up",
            f"history_level_{level}",
            body_key=f"history_level_{level}_body",
            payload={"level": level, "reason": reason},
            conn=conn,
        )

    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET planet_level = ?, planet_xp = ? WHERE id = ?;",
        (int(level), int(xp), int(planet_id)),
    )

    return {
        "planet_id": int(planet_id),
        "xp_gained": gained,
        "planet_level": level,
        "planet_xp": xp,
        "levels_gained": levels_gained,
        "xp_next_level": xp_threshold_for_level(level + 1) if level < MAX_PLANET_LEVEL else None,
        "diversity_bonus": bonus,
    }


def level_progress(planet_id: int, conn: sqlite3.Connection) -> Tuple[int, int, int]:
    planet = get_planet_row(planet_id, conn=conn) or {}
    level = int(planet.get("planet_level") or 1)
    xp = int(planet.get("planet_xp") or 0)
    return level, xp, xp_to_next_level(level, xp)
