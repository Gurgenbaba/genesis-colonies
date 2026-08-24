"""
Canonical integer display formatting (full + compact German locale).

Used by Jinja filters, PlayerCard, ranking API consumers, and mirrored in static/main.js.
Player-facing integer formatting must never emit scientific notation.
"""

from __future__ import annotations

import re
from typing import Dict

COMPACT_THRESHOLD = 10_000_000
FULL_FALLBACK_THRESHOLD = 10**33

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


def _format_compact_body(abs_value: int, div: int) -> str:
    """One-decimal compact mantissa using integer arithmetic only."""
    abs_n = abs(int(abs_value))
    divisor = max(1, int(div))
    tenths = (abs_n * 10 + divisor // 2) // divisor
    whole, tenth = divmod(tenths, 10)
    return str(whole) if tenth == 0 else f"{whole},{tenth}"


_COMPACT_TIERS = (
    (10**30, "Q"),
    (10**27, "R"),
    (10**24, "Y"),
    (10**21, "Z"),
    (10**18, "E"),
    (10**15, "P"),
    (10**12, "Bio."),
    (10**9, "Mrd."),
    (10**6, "Mio."),
    (10**3, "Tsd."),
)


def fmt_int_compact(value: object) -> str:
    """Compact arbitrary-precision display that never emits scientific notation."""
    n = parse_int_number(value)
    abs_n = abs(n)
    if abs_n < COMPACT_THRESHOLD:
        return fmt_int(n)

    # Quetta is the highest compact tier we expose. Beyond it, prefer the
    # exact grouped integer over debug-looking scientific notation.
    if abs_n >= FULL_FALLBACK_THRESHOLD:
        return fmt_int(n)

    sign = "-" if n < 0 else ""
    for div, suffix in _COMPACT_TIERS:
        if abs_n >= div:
            return f"{sign}{_format_compact_body(abs_n, div)} {suffix}"

    return fmt_int(n)


def fmt_int_parts(value: object) -> Dict[str, str]:
    """Return {display, full} for compact UI with exact tooltip fallback."""
    n = parse_int_number(value)
    full = fmt_int(n)
    display = fmt_int_compact(n)
    return {"display": display, "full": full}
