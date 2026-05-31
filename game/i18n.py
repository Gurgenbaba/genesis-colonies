"""Server-side translations for game logic (default locale: de)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
_DEFAULT_LOCALE = "de"


@lru_cache(maxsize=4)
def _load_locale(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def tr(key: str, default: str | None = None, **fmt: object) -> str:
    """Translate key from locale JSON; optional %(name)s formatting."""
    text = _load_locale(_DEFAULT_LOCALE).get(key)
    if text is None:
        text = default if default is not None else key
    if not fmt:
        return text
    try:
        return text % fmt
    except Exception:
        return text


def fmt_int(value: object) -> str:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return str(value)
    return f"{n:,}".replace(",", ".")
