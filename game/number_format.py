"""
Canonical integer display formatting (full + compact German locale).

Used by Jinja filters, PlayerCard, ranking API consumers, and mirrored in static/main.js.
"""

from __future__ import annotations

import re
from typing import Dict

COMPACT_THRESHOLD = 10_000_000

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


def _format_compact_mantissa(val: float) -> str:
    abs_val = abs(val)
    if abs_val >= 1000:
        body = f"{val:.0f}"
    elif abs_val >= 1:
        body = f"{val:.1f}"
    else:
        body = f"{val:.2f}"
    if "." in body:
        body = body.rstrip("0").rstrip(".")
    return body.replace(".", ",")


def _format_scientific_int(value: int, *, significant_digits: int = 3) -> str:
    """Scientific notation without float conversion (e.g. 1,23e50)."""
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    take = max(1, int(significant_digits))
    head = digits[:take].ljust(take, "0")
    fraction = head[1:].rstrip("0")
    mantissa = head[0] + (("," + fraction) if fraction else "")
    return f"{sign}{mantissa}e{len(digits) - 1}"


def fmt_int_compact(value: object) -> str:
    """Compact arbitrary-precision display; huge values never become fake infinity."""
    n = parse_int_number(value)
    abs_n = abs(n)
    if abs_n < COMPACT_THRESHOLD:
        return fmt_int(n)
    if abs_n >= 10**15:
        return _format_scientific_int(n)

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
    """Return {display, full} for compact UI with exact tooltip fallback."""
    n = parse_int_number(value)
    full = fmt_int(n)
    display = fmt_int_compact(n)
    return {"display": display, "full": full}
