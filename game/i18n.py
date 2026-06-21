"""Server-side translations for game logic and inbox notifications."""

from __future__ import annotations

import contextvars
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

_I18N_PCT_RE = re.compile(r"%\(([^)]+)\)s")
_I18N_BRACE_RE = re.compile(r"\{([^}]+)\}")

from .db import column_exists, db

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LOCALE = "de"
SUPPORTED_LOCALES = frozenset({"de", "en"})

_current_locale: contextvars.ContextVar[str] = contextvars.ContextVar(
    "locale", default=DEFAULT_LOCALE
)


@lru_cache(maxsize=4)
def _load_locale(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


def normalize_locale(locale: str | None) -> str:
    loc = str(locale or DEFAULT_LOCALE).strip().lower()
    return loc if loc in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_locale_dict(locale: str | None = None) -> dict[str, str]:
    loc = normalize_locale(locale)
    primary = _load_locale(loc)
    if loc == DEFAULT_LOCALE:
        return primary
    fallback = _load_locale(DEFAULT_LOCALE)
    merged = dict(fallback)
    merged.update(primary)
    return merged


def current_locale() -> str:
    return normalize_locale(_current_locale.get())


def set_request_locale(locale: str | None) -> str:
    loc = normalize_locale(locale)
    _current_locale.set(loc)
    return loc


def ensure_locale_schema(conn=None) -> None:
    own = conn is None
    c = conn or db()
    try:
        if not column_exists(c, "users", "locale"):
            cur = c.cursor()
            cur.execute("ALTER TABLE users ADD COLUMN locale TEXT NOT NULL DEFAULT 'de';")
        if own:
            c.commit()
    finally:
        if own:
            c.close()


def get_player_locale(player_id: int, *, conn=None) -> str:
    pid = int(player_id or 0)
    if pid <= 0:
        return DEFAULT_LOCALE
    own = conn is None
    c = conn or db()
    try:
        ensure_locale_schema(c)
        row = c.execute("SELECT locale FROM users WHERE id = ? LIMIT 1;", (pid,)).fetchone()
        if not row:
            return DEFAULT_LOCALE
        return normalize_locale(row["locale"])
    except Exception:
        return DEFAULT_LOCALE
    finally:
        if own:
            c.close()


def set_player_locale(player_id: int, locale: str, *, conn=None) -> str:
    pid = int(player_id or 0)
    loc = normalize_locale(locale)
    if pid <= 0:
        return loc
    own = conn is None
    c = conn or db()
    try:
        ensure_locale_schema(c)
        c.execute("UPDATE users SET locale = ? WHERE id = ?;", (loc, pid))
        if own:
            c.commit()
    finally:
        if own:
            c.close()
    return loc


def format_i18n(text: str, **fmt: object) -> str:
    """Interpolate %(name)s and {name} placeholders (mirrors client tf())."""
    if not fmt:
        return text

    def _pct_sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in fmt:
            return match.group(0)
        val = fmt[key]
        return "" if val is None else str(val)

    def _brace_sub(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in fmt:
            return match.group(0)
        val = fmt[key]
        return "" if val is None else str(val)

    if _I18N_PCT_RE.search(text):
        try:
            return text % fmt
        except (KeyError, TypeError, ValueError):
            text = _I18N_PCT_RE.sub(_pct_sub, text)

    if _I18N_BRACE_RE.search(text):
        try:
            return text.format(**{k: ("" if v is None else v) for k, v in fmt.items()})
        except (KeyError, ValueError):
            text = _I18N_BRACE_RE.sub(_brace_sub, text)

    return text


def tr(key: str, default: str | None = None, *, locale: str | None = None, **fmt: object) -> str:
    """Translate key from locale JSON; optional %(name)s / {name} formatting."""
    loc = normalize_locale(locale) if locale is not None else current_locale()
    text = get_locale_dict(loc).get(key)
    if text is None:
        text = default if default is not None else key
    return format_i18n(text, **fmt)


def fmt_int(value: object, *, locale: str | None = None) -> str:
    del locale  # number format stays de-DE style for now
    from .number_format import fmt_int as _fmt

    return _fmt(value)
