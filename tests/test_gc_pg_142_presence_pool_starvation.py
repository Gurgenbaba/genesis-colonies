"""Issue #142 — authenticated presence must never nest pool checkouts on lock soft-fail."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import game.presence as presence

ROOT = Path(__file__).resolve().parents[1]


class _FakeLockError(Exception):
    pass


_FakeLockError.__name__ = "LockNotAvailable"


class _FakeConn:
    def __init__(self, *, lock_on_update: bool = True) -> None:
        self.closed = False
        self.rolled_back = False
        self.committed = False
        self.lock_on_update = bool(lock_on_update)
        self.sql: list[str] = []

    def execute(self, sql, params=None):  # noqa: ANN001
        text = str(sql)
        self.sql.append(text)
        if text.startswith("SELECT last_seen"):
            return SimpleNamespace(fetchone=lambda: {"last_seen": 0})
        if text.startswith("UPDATE players SET last_seen") and self.lock_on_update:
            raise _FakeLockError("canceling statement due to lock timeout")
        return SimpleNamespace(fetchone=lambda: None)

    def cursor(self):
        return self

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _patch_presence_basics(monkeypatch, conn, *, local_marks):
    from game import inactive_autoplay, models

    checkouts = {"n": 0}

    def fake_db():
        checkouts["n"] += 1
        if checkouts["n"] > 1:
            raise AssertionError("nested/second pool checkout from presence path")
        return conn

    monkeypatch.setattr(presence, "db", fake_db)
    monkeypatch.setattr(presence, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(presence, "begin_write_transaction", lambda c: None)
    monkeypatch.setattr(presence, "commit", lambda c: c.commit())
    monkeypatch.setattr(presence, "rollback", lambda c: c.rollback())
    monkeypatch.setattr(models, "_now_ts", lambda: 1_000)
    monkeypatch.setattr(models, "_presence_touch_interval_sec", lambda: 30)
    monkeypatch.setattr(models, "_presence_local_fresh", lambda *a, **k: False)
    monkeypatch.setattr(
        models,
        "_presence_local_mark",
        lambda player_id, **kwargs: local_marks.append(int(player_id)),
    )
    monkeypatch.setattr(
        inactive_autoplay,
        "player_on_inactive_autoplay_roster",
        lambda player_id, *, conn: False,
    )
    return checkouts


def test_presence_lock_softfail_uses_one_checkout(monkeypatch):
    """Regression: lock fallback must not hold one pool conn while asking for another."""
    conn = _FakeConn(lock_on_update=True)
    local_marks: list[int] = []
    checkouts = _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)

    presence.touch_player_online(7)

    assert checkouts["n"] == 1
    assert conn.closed is True
    assert conn.rolled_back is True
    assert conn.committed is False
    assert local_marks == []  # next authenticated request must retry the touch
    assert any("SET LOCAL lock_timeout = '250ms'" in sql for sql in conn.sql)


def test_roster_release_failure_keeps_successful_presence_write(monkeypatch):
    """Optional roster failure is SAVEPOINT-isolated; last_seen still commits."""
    from game import inactive_autoplay

    conn = _FakeConn(lock_on_update=False)
    local_marks: list[int] = []
    checkouts = _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)

    monkeypatch.setattr(
        inactive_autoplay,
        "release_active_player_from_roster",
        lambda player_id, *, conn: (_ for _ in ()).throw(RuntimeError("runtime_state unavailable")),
    )

    presence.touch_player_online(7)

    assert checkouts["n"] == 1
    assert conn.closed is True
    assert conn.rolled_back is False
    assert conn.committed is True
    assert local_marks == [7]
    assert "SAVEPOINT gc_presence_roster" in conn.sql
    assert "ROLLBACK TO SAVEPOINT gc_presence_roster" in conn.sql
    assert "RELEASE SAVEPOINT gc_presence_roster" in conn.sql


def test_auth_guards_use_non_nested_presence_owner():
    source = (ROOT / "game" / "auth.py").read_text(encoding="utf-8")
    assert "from .presence import touch_player_online" in source
    models_import = source.split("from .models import (", 1)[1].split(")", 1)[0]
    assert "touch_player_online" not in models_import


def test_presence_lock_handler_has_no_db_checkout():
    source = (ROOT / "game" / "presence.py").read_text(encoding="utf-8")
    lock_block = source.split("if is_db_lock_error(exc):", 1)[1].split(
        "logger.exception", 1
    )[0]
    assert "db()" not in lock_block
    assert "_release_roster_best_effort" not in source
    assert "SAVEPOINT gc_presence_roster" in source
