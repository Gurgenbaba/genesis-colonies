"""
Canonical player-facing integer display formatting (exact grouped German locale).

Used by Jinja filters, PlayerCard, ranking API consumers, and mirrored in static/main.js.
Player-facing integer formatting must never emit scientific notation.
"""

from __future__ import annotations

import re
from typing import Dict

# de-DE grouped integers: 999.999 / 1.000 / 10.000.000
_DE_GROUPED_INT_RE = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_int_number(value: object, *, default: int = 0) -> int:
    """Parse ints from raw numbers or de-DE grouped strings — never substring-truncate."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value == value:  # NaN
            return default
        return int(round(value))

    raw = str(value).strip()
    if not raw:
        return default

    cleaned = raw.replace(" ", "")
    if cleaned.isdigit() or (cleaned.startswith("-") and cleaned[1:].isdigit()):
        try:
            return int(cleaned)
        except ValueError:
            return default

    if _DE_GROUPED_INT_RE.match(cleaned):
        try:
            return int(cleaned.replace(".", ""))
        except ValueError:
            return default

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        return int(round(float(cleaned)))
    except (TypeError, ValueError, OverflowError):
        return default


def fmt_int(value: object) -> str:
    """Full grouped arbitrary-precision integer: 149.539.413.840."""
    n = parse_int_number(value)
    return f"{n:,}".replace(",", ".")


def fmt_int_compact(value: object) -> str:
    """Compatibility alias: player-facing integers are always exact grouped digits."""
    return fmt_int(value)


def fmt_int_parts(value: object) -> Dict[str, str]:
    """Return {display, full} for compact UI with exact tooltip fallback."""
    n = parse_int_number(value)
    full = fmt_int(n)
    display = fmt_int_compact(n)
    return {"display": display, "full": full}
