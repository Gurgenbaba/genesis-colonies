"""Server-side translations for game logic and inbox notifications."""

from __future__ import annotations

import contextvars
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import has_request_context, session

_I18N_PCT_RE = re.compile(r"%\(([^)]+)\)s")
_I18N_BRACE_RE = re.compile(r"\{([^}]+)\}")

from .db import column_exists, db

_LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"
DEFAULT_LOCALE = "de"
FALLBACK_LOCALE = "en"

SUPPORTED_LANGUAGES: dict[str, dict[str, str]] = {
    "de": {"label": "Deutsch", "flag": "🇩🇪", "flag_code": "de"},
    "en": {"label": "English", "flag": "🇬🇧", "flag_code": "gb"},
    "fr": {"label": "Français", "flag": "🇫🇷", "flag_code": "fr"},
    "es": {"label": "Español", "flag": "🇪🇸", "flag_code": "es"},
    "pl": {"label": "Polski", "flag": "🇵🇱", "flag_code": "pl"},
    "tr": {"label": "Türkçe", "flag": "🇹🇷", "flag_code": "tr"},
    "ru": {"label": "Русский", "flag": "🇷🇺", "flag_code": "ru"},
    "pt": {"label": "Português", "flag": "🇵🇹", "flag_code": "pt"},
}

SUPPORTED_LOCALES = frozenset(SUPPORTED_LANGUAGES)

_current_locale: contextvars.ContextVar[str] = contextvars.ContextVar(
    "locale", default=DEFAULT_LOCALE
)

# GC-PG-HIGHSPEED: authenticated requests previously opened a fresh database
# checkout in app.before_request merely to read users.locale. Keep the user's
# authoritative locale in the signed Flask session after the first read and
# refresh it immediately when the option changes. Background jobs and callers
# that explicitly pass a connection continue to read the database directly.
_SESSION_LOCALE_KEY = "gc_player_locale"
_SESSION_LOCALE_PLAYER_KEY = "gc_player_locale_player_id"


@lru_cache(maxsize=len(SUPPORTED_LOCALES) + 2)
def _load_locale(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return {}


_locale_mtimes: dict[str, float] = {}


def clear_locale_cache() -> None:
    """Drop cached locale JSON (hot-reload after locales/*.json edits)."""
    _load_locale.cache_clear()
    _locale_mtimes.clear()


def _locale_mtime(locale: str) -> float:
    path = _LOCALES_DIR / f"{locale}.json"
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def normalize_locale(locale: str | None) -> str:
    loc = str(locale or DEFAULT_LOCALE).strip().lower()
    return loc if loc in SUPPORTED_LOCALES else DEFAULT_LOCALE


def get_locale_dict(locale: str | None = None) -> dict[str, str]:
    loc = normalize_locale(locale)
    mtime = _locale_mtime(loc)
    if _locale_mtimes.get(loc) != mtime:
        # File changed on disk — invalidate this locale (+ en fallback for merges).
        _load_locale.cache_clear()
        _locale_mtimes.clear()
        _locale_mtimes[loc] = mtime
        _locale_mtimes[FALLBACK_LOCALE] = _locale_mtime(FALLBACK_LOCALE)
    primary = _load_locale(loc)
    if loc in (DEFAULT_LOCALE, FALLBACK_LOCALE):
        return primary
    fallback = _load_locale(FALLBACK_LOCALE)
    merged = dict(fallback)
    merged.update(primary)
    return merged


def current_locale() -> str:
    return normalize_locale(_current_locale.get())


def set_request_locale(locale: str | None) -> str:
    loc = normalize_locale(locale)
    _current_locale.set(loc)
    return loc


def _session_player_locale(player_id: int) -> str | None:
    """Return the request-session locale only when it belongs to this player."""
    if not has_request_context():
        return None
    try:
        cached_pid = int(session.get(_SESSION_LOCALE_PLAYER_KEY) or 0)
        if cached_pid != int(player_id):
            return None
        raw = session.get(_SESSION_LOCALE_KEY)
        if raw is None:
            return None
        return normalize_locale(str(raw))
    except Exception:
        return None


def _store_session_player_locale(player_id: int, locale: str) -> None:
    if not has_request_context():
        return
    try:
        session[_SESSION_LOCALE_PLAYER_KEY] = int(player_id)
        session[_SESSION_LOCALE_KEY] = normalize_locale(locale)
    except Exception:
        pass


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

    # app.before_request calls this without a connection on every authenticated
    # HTTP request. After the first authoritative read, avoid another PG pool
    # checkout entirely. Explicit-connection callers intentionally bypass this
    # request cache so worker/gameplay logic keeps normal DB semantics.
    if conn is None:
        cached = _session_player_locale(pid)
        if cached is not None:
            return cached

    own = conn is None
    c = conn or db()
    try:
        ensure_locale_schema(c)
        row = c.execute("SELECT locale FROM users WHERE id = ? LIMIT 1;", (pid,)).fetchone()
        if not row:
            loc = DEFAULT_LOCALE
        else:
            loc = normalize_locale(row["locale"])
        if own:
            _store_session_player_locale(pid, loc)
        return loc
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
        # Keep the browser request cache immediately coherent with an options
        # change. No TTL/staleness window is required for the normal UI path.
        _store_session_player_locale(pid, loc)
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
