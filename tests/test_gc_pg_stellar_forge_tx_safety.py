"""GC-PG-FORGE-TX-001 — optional Forge hooks must not poison parent PG tx."""

from __future__ import annotations

import pytest

import game.stellar_forge.safe_hooks as hooks


class LockNotAvailable(Exception):
    pass


class _FakePgConn:
    def __init__(self) -> None:
        self.aborted = False
        self.statements: list[str] = []

    def execute(self, sql: str, params=None):
        text = str(sql).strip()
        upper = text.upper()
        self.statements.append(upper)
        if upper.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False
            return self
        if upper.startswith("RELEASE SAVEPOINT"):
            return self
        if upper.startswith("SAVEPOINT"):
            if self.aborted:
                raise RuntimeError("current transaction is aborted")
            return self
        if self.aborted:
            raise RuntimeError("current transaction is aborted")
        return self


def _poison_with(exc_type):
    def _impl(planet_id, protocol, amount, *, conn, now=None):
        conn.aborted = True
        raise exc_type("canceling statement due to lock timeout")

    return _impl


def test_pg_lock_timeout_soft_skips_and_restores_parent_transaction(monkeypatch):
    conn = _FakePgConn()
    monkeypatch.setattr(hooks, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(hooks, "_record_operational_progress", _poison_with(LockNotAvailable))

    # A transient optional Forge write must not fail the expedition/world-boss
    # transaction that owns this connection.
    hooks.record_operational_progress(7, "exploration", 1, conn=conn, now=123.0)

    assert conn.aborted is False
    assert any(s.startswith("SAVEPOINT GC_STELLAR_FORGE_OPERATIONAL_PROGRESS") for s in conn.statements)
    assert any(s.startswith("ROLLBACK TO SAVEPOINT GC_STELLAR_FORGE_OPERATIONAL_PROGRESS") for s in conn.statements)
    assert any(s.startswith("RELEASE SAVEPOINT GC_STELLAR_FORGE_OPERATIONAL_PROGRESS") for s in conn.statements)
    conn.execute("SELECT 1")  # parent transaction is still usable


def test_pg_unknown_failure_is_reraised_after_parent_transaction_recovery(monkeypatch):
    conn = _FakePgConn()
    monkeypatch.setattr(hooks, "get_db_backend", lambda: "postgres")
    monkeypatch.setattr(hooks, "_record_operational_progress", _poison_with(ValueError))

    with pytest.raises(ValueError):
        hooks.record_operational_progress(7, "exploration", 1, conn=conn, now=123.0)

    assert conn.aborted is False
    conn.execute("SELECT 1")


def test_sqlite_path_does_not_add_savepoint_overhead(monkeypatch):
    conn = _FakePgConn()
    calls = []
    monkeypatch.setattr(hooks, "get_db_backend", lambda: "sqlite")
    monkeypatch.setattr(
        hooks,
        "_record_operational_progress",
        lambda planet_id, protocol, amount, *, conn, now=None: calls.append(
            (planet_id, protocol, amount, now)
        ),
    )

    hooks.record_operational_progress(9, "exploration", 2, conn=conn, now=456.0)

    assert calls == [(9, "exploration", 2, 456.0)]
    assert conn.statements == []
