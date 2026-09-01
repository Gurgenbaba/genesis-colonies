"""Issue #142 / GC-PG-HIGHSPEED-001C presence regression gates."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import game.presence as presence
from game import presence_store

ROOT = Path(__file__).resolve().parents[1]


class _FakeLockError(Exception):
    pass


_FakeLockError.__name__ = "LockNotAvailable"


class _FakeConn:
    def __init__(self, *, lock_on_touch: bool = True, presence_seen: int = 0) -> None:
        self.closed = False
        self.rolled_back = False
        self.committed = False
        self.lock_on_touch = bool(lock_on_touch)
        self.presence_seen = int(presence_seen)
        self.sql: list[str] = []

    def execute(self, sql, params=None):
        text = str(sql)
        self.sql.append(text)
        if text.startswith("SELECT last_seen"):
            return SimpleNamespace(fetchone=lambda: {"last_seen": self.presence_seen})
        if "INSERT INTO player_presence" in text and self.lock_on_touch:
            raise _FakeLockError("canceling statement due to lock timeout")
        return SimpleNamespace(fetchone=lambda: None)

    def cursor(self): return self
    def commit(self) -> None: self.committed = True
    def rollback(self) -> None: self.rolled_back = True
    def close(self) -> None: self.closed = True


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
    monkeypatch.setattr(models, "_presence_local_mark", lambda player_id, **kwargs: local_marks.append(int(player_id)))
    monkeypatch.setattr(inactive_autoplay, "player_on_inactive_autoplay_roster", lambda player_id, *, conn: False)
    return checkouts


def test_presence_lock_softfail_uses_one_checkout(monkeypatch):
    conn = _FakeConn(lock_on_touch=True)
    local_marks = []
    checkouts = _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)
    presence.touch_player_online(7)
    assert checkouts["n"] == 1
    assert conn.closed and conn.rolled_back and not conn.committed
    assert local_marks == []
    assert any("SET LOCAL lock_timeout = '250ms'" in sql for sql in conn.sql)
    assert not any("UPDATE players SET last_seen" in sql for sql in conn.sql)


def test_roster_release_failure_keeps_successful_presence_write(monkeypatch):
    from game import inactive_autoplay
    conn = _FakeConn(lock_on_touch=False)
    local_marks = []
    checkouts = _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)
    monkeypatch.setattr(inactive_autoplay, "release_active_player_from_roster", lambda player_id, *, conn: (_ for _ in ()).throw(RuntimeError("runtime_state unavailable")))
    presence.touch_player_online(7)
    assert checkouts["n"] == 1
    assert conn.closed and not conn.rolled_back and conn.committed
    assert local_marks == [7]
    assert "SAVEPOINT gc_presence_roster" in conn.sql
    assert "ROLLBACK TO SAVEPOINT gc_presence_roster" in conn.sql
    assert "RELEASE SAVEPOINT gc_presence_roster" in conn.sql
    assert any("INSERT INTO player_presence" in sql for sql in conn.sql)
    assert "SAVEPOINT gc_presence_legacy" in conn.sql
    assert any("UPDATE players SET last_seen" in sql for sql in conn.sql)


def test_recent_dedicated_presence_skips_legacy_player_row_write(monkeypatch):
    conn = _FakeConn(lock_on_touch=False, presence_seen=900)
    local_marks = []
    _patch_presence_basics(monkeypatch, conn, local_marks=local_marks)
    presence.touch_player_online(7)
    assert conn.committed is True
    assert any("INSERT INTO player_presence" in sql for sql in conn.sql)
    assert not any("UPDATE players SET last_seen" in sql for sql in conn.sql)
    assert "SAVEPOINT gc_presence_legacy" not in conn.sql


def test_legacy_sync_cadence_stays_inside_online_window():
    assert presence_store.LEGACY_SYNC_INTERVAL_SEC < 5 * 60
    assert presence_store.should_sync_legacy_last_seen(previous_seen=0, now=1_000)
    assert presence_store.should_sync_legacy_last_seen(previous_seen=700, now=1_000)
    assert not presence_store.should_sync_legacy_last_seen(previous_seen=900, now=1_000)


def test_postgres_store_never_references_players_on_canonical_touch():
    conn = _FakeConn(lock_on_touch=False)
    presence_store.touch_presence(conn, 11, now=1234, touch_before=1200, backend="postgres")
    sql = "\n".join(conn.sql).lower()
    assert "insert into player_presence" in sql
    assert "update players" not in sql
    assert "from players" not in sql


def test_sqlite_store_keeps_legacy_path():
    conn = _FakeConn(lock_on_touch=False)
    presence_store.touch_presence(conn, 11, now=1234, touch_before=1200, backend="sqlite")
    assert any("UPDATE players SET last_seen" in sql for sql in conn.sql)


def test_presence_migration_is_idempotent_partial_schema_safe_and_non_destructive():
    migration = (ROOT / "migrations" / "158_player_presence.sql").read_text(encoding="utf-8")
    assert "REFERENCES players" not in migration
    assert "REFERENCES users(id) ON DELETE CASCADE" in migration
    assert "DROP TABLE" not in migration.upper()
    assert "DROP COLUMN" not in migration.upper()
    assert "FROM players" not in migration

    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(migration)
        conn.executescript(migration)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')").fetchall()}
        assert "player_presence" in names
        assert "idx_player_presence_last_seen" in names
    finally:
        conn.close()

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        conn.execute("CREATE TABLE players (id INTEGER PRIMARY KEY, last_seen INTEGER)")
        conn.execute("INSERT INTO users (id) VALUES (7)")
        conn.execute("INSERT INTO players (id, last_seen) VALUES (7, 777)")
        conn.executescript(migration)
        conn.execute("INSERT INTO player_presence (player_id, last_seen, updated_at) VALUES (7, 888, 888)")
        conn.execute("DELETE FROM users WHERE id = 7")
        assert conn.execute("SELECT COUNT(*) FROM player_presence").fetchone() == (0,)
        assert conn.execute("SELECT last_seen FROM players WHERE id = 7").fetchone() == (777,)
    finally:
        conn.close()


def test_auth_guards_use_non_nested_presence_owner():
    source = (ROOT / "game" / "auth.py").read_text(encoding="utf-8")
    assert "from .presence import touch_player_online" in source
    models_import = source.split("from .models import (", 1)[1].split(")", 1)[0]
    assert "touch_player_online" not in models_import


def test_presence_lock_handler_has_no_db_checkout():
    source = (ROOT / "game" / "presence.py").read_text(encoding="utf-8")
    lock_block = source.split("if is_db_lock_error(exc):", 1)[1].split("logger.exception", 1)[0]
    assert "db()" not in lock_block
    assert "_release_roster_best_effort" not in source
