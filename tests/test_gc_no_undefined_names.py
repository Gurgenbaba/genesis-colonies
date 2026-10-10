"""Static guard: no undefined names in app.py / game/ (pyflakes).

A function that references a name that was never imported raises NameError only when
that branch runs - and several of them sat in rarely used or error paths for weeks:
support replies, the notification heartbeat (silently reported 0 unread), pirate base
rewards, an error handler in buildings. Skipped when pyflakes is not installed.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pyflakes_api = pytest.importorskip("pyflakes.api")
pyflakes_messages = pytest.importorskip("pyflakes.messages")

ROOT = Path(__file__).resolve().parents[1]
# Dead code: shadowed by the redefinitions later in the module (ranking_core.py:2399/2408).
ALLOWED = {("game/ranking_core.py", "MAX_SCORE")}


class _Collector:
    def __init__(self) -> None:
        self.found: list[tuple[str, str, int]] = []

    def unexpectedError(self, filename, msg):  # pragma: no cover
        raise AssertionError(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):  # pragma: no cover
        raise AssertionError(f"{filename}:{lineno}: {msg}")

    def flake(self, message):
        if isinstance(message, pyflakes_messages.UndefinedName):
            rel = Path(message.filename).resolve().relative_to(ROOT).as_posix()
            self.found.append((rel, message.message_args[0], message.lineno))


def test_no_undefined_names_in_app_and_game():
    collector = _Collector()
    files = [ROOT / "app.py", *sorted((ROOT / "game").rglob("*.py"))]
    for path in files:
        pyflakes_api.check(path.read_text(encoding="utf-8"), str(path), collector)
    offenders = [(f, name, line) for f, name, line in collector.found if (f, name) not in ALLOWED]
    assert not offenders, f"undefined names (NameError at runtime): {offenders}"
