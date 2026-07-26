"""
Canonical human duration formatting (GC HUD style).

Fixed game calendar (not civil months): y=365d, mo=30d, w=7d.

Adaptive ladders — never mix ``mo`` and ``w`` in one label.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

# Fixed lengths — intentional game calendar, not Gregorian months.
SEC_MINUTE = 60
SEC_HOUR = 3600
SEC_DAY = 86400
SEC_WEEK = 7 * SEC_DAY
SEC_MONTH = 30 * SEC_DAY
SEC_YEAR = 365 * SEC_DAY

UnitTable = Tuple[Tuple[str, int], ...]


def _unit_table_for(sec: int) -> UnitTable:
    """Pick a non-overlapping unit ladder for the magnitude of ``sec``."""
    if sec >= SEC_YEAR:
        return (
            ("y", SEC_YEAR),
            ("mo", SEC_MONTH),
            ("d", SEC_DAY),
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    if sec >= 90 * SEC_DAY:
        return (
            ("mo", SEC_MONTH),
            ("d", SEC_DAY),
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    if sec >= 30 * SEC_DAY:
        # Season-scale: plain days (no mo/w overlap).
        return (
            ("d", SEC_DAY),
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    if sec >= SEC_WEEK:
        # 7–29d: weeks make sense; never paired with months.
        return (
            ("w", SEC_WEEK),
            ("d", SEC_DAY),
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    if sec >= SEC_DAY:
        return (
            ("d", SEC_DAY),
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    if sec >= SEC_HOUR:
        return (
            ("h", SEC_HOUR),
            ("min", SEC_MINUTE),
            ("s", 1),
        )
    return (
        ("min", SEC_MINUTE),
        ("s", 1),
    )


def format_duration_human(
    seconds: int | float | None,
    *,
    max_parts: int = 3,
    units: Sequence[Tuple[str, int]] | None = None,
) -> str:
    """
    Format a duration for HUD / Season / Timekeeper labels.

    Examples:
      45 → "45s"
      125 → "2min 5s"
      7380 → "2h 3min"
      10d → "1w 3d"
      5182530 → "59d 22h"  (season-scale; no mo+w)
      100d → "3mo 10d"
    """
    sec = max(0, int(seconds or 0))
    if sec <= 0:
        return "0s"

    parts_limit = max(1, int(max_parts or 3))
    table = tuple(units) if units is not None else _unit_table_for(sec)
    rem = sec
    parts: List[str] = []
    for label, size in table:
        if size <= 0:
            continue
        if rem < size and not parts:
            continue
        qty, rem = divmod(rem, size)
        if qty <= 0:
            continue
        parts.append(f"{qty}{label}")
        if len(parts) >= parts_limit:
            break

    if not parts:
        return f"{sec}s"
    return " ".join(parts)
