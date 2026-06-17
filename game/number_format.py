"""
Canonical integer display formatting (full + compact German locale).

Used by Jinja filters, PlayerCard, ranking API consumers, and mirrored in static/main.js.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple

COMPACT_THRESHOLD = 10_000_000
COMPACT_INFINITY = 10**18

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

    # de-DE grouped with decimal comma: 1.234,56 — rare for build amounts
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        return int(round(float(cleaned)))
    except (TypeError, ValueError):
        return default


def fmt_int(value: object) -> str:
    """Full grouped integer: 149.539.413.840"""
    n = parse_int_number(value)
    return f"{n:,}".replace(",", ".")


def _format_compact_mantissa(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1000:
        body = f"{val:.0f}"
    elif abs_val >= 10:
        body = f"{val:.1f}"
    elif abs_val >= 1:
        body = f"{val:.1f}"
    else:
        body = f"{val:.2f}"
    if "." in body:
        body = body.rstrip("0").rstrip(".")
    return body.replace(".", ",")


def fmt_int_compact(value: object) -> str:
    """Compact German display: 149,5 Mrd."""
    n = parse_int_number(value)
    abs_n = abs(n)
    if abs_n < COMPACT_THRESHOLD:
        return fmt_int(n)
    if abs_n >= COMPACT_INFINITY:
        return "∞"

    sign = "-" if n < 0 else ""
    if abs_n >= 10**12:
        suffix, div = "Bio.", 10**12
    elif abs_n >= 10**9:
        suffix, div = "Mrd.", 10**9
    elif abs_n >= 10**6:
        suffix, div = "Mio.", 10**6
    else:
        suffix, div = "Tsd.", 10**3

    val = abs_n / div
    body = _format_compact_mantissa(val)
    return f"{sign}{body} {suffix}"


def fmt_int_parts(value: object) -> Dict[str, str]:
    """Return {display, full} for compact UI with tooltip fallback."""
    n = parse_int_number(value)
    full = fmt_int(n)
    display = fmt_int_compact(n)
    return {"display": display, "full": full}
