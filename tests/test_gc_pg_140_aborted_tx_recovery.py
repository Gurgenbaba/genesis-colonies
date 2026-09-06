"""Issue #140 — caller-owned poll TX recovery via SAVEPOINT (no full rollback)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from game.db import begin_write_transaction, get_db_backend, is_db_lock_error
from game.logic import read_player_live_state_for_poll

ROOT = Path(__file__).resolve().parents[1]


class _FakeLockError(Exception):
    """Mirrors psycopg.errors.LockNotAvailable for soft-fail classification."""


_FakeLockError.__name__ = "LockNotAvailable"


class _CallerOwnedConn:
    """Minimal conn that records SAVEPOINT / SQL and can inject a lock mid-write."""

    def __init__(self) -> None:
        self.statements: List[str] = []
        self.in_transaction = True
        self._fail_on_finish = False
        self._aborted = False
        self._savepoints: List[str] = []
        self._marker_written = False

    def execute(self, sql: str, params: Any = None):
        text = str(sql or "").strip()
        upper = text.upper()
        self.statements.append(text)

        if self._aborted and not upper.startswith("ROLLBACK TO SAVEPOINT"):
            if upper.startswith("RELEASE SAVEPOINT"):
                pass
            elif "SAVEPOINT" in upper and not upper.startswith("ROLLBACK"):
                raise RuntimeError("current transaction is aborted")
            else:
                err = RuntimeError("current transaction is aborted")
                err.__class__ = type(
                    "InFailedSqlTransaction", (RuntimeError,), {}
                )
                raise err

        if upper.startswith("SAVEPOINT "):
            name = text.split()[-1]
            self._savepoints.append(name)
            return self

        if upper.startswith("RELEASE SAVEPOINT"):
            name = text.split()[-1]
            if name in self._savepoints:
                self._savepoints.remove(name)
            return self

        if upper.startswith("ROLLBACK TO SAVEPOINT"):
            name = text.split()[-1]
            self._aborted = False
            return self

        if upper.startswith("BEGIN"):
            self.in_transaction = True
            return self

        if self._fail_on_finish and "FINISH_INJECT" in upper:
            self._aborted = True
            raise _FakeLockError("canceling statement due to lock timeout")

        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self) -> None:
        return None


def test_is_db_lock_error_recognizes_fake_lock():
    assert is_db_lock_error(_FakeLockError("lock timeout"))


def test_poll_source_uses_caller_owned_savepoint():
    source = (ROOT / "game" / "logic.py").read_text(encoding="utf-8")
    block = source.split("def read_player_live_state_for_poll(")[1].split(
        "\ndef refresh_player_live_state(", 1
    )[0]
    assert "gc_poll_live_write" in block
    assert "ROLLBACK TO SAVEPOINT" in block
    assert "process_player_due_fleets_now(uid, now=now)" in block
    assert "manage_transaction=bool(own_conn)" not in block
    assert "mark_request_poll_safety_net_write" in block
    assert "if own_conn:" in block and "commit(conn)" in block
    # Must not blanket-rollback caller-owned connections on lock soft-fail.
    assert "if own_conn:\n                try:\n                    rollback(conn)" in block


def test_refresh_source_uses_nested_side_effect_savepoints():
    source = (ROOT / "game" / "logic.py").read_text(encoding="utf-8")
    block = source.split("def refresh_player_live_state(")[1].split(
        "\ndef update_planet_resources(", 1
    )[0]
    assert "gc_refresh_live" in block
    assert "_run_optional_side_effect" in block
    assert "_locked_read_only_fallback" in block
    assert "_soft_recover_refresh_side_effect" not in block


def test_entrypoint_closes_pool_after_short_lived_seed():
    source = (ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "ensure_changelog_seeded" in source
    assert "close_pool()" in source
    assert source.count("close_pool()") >= 2


def test_caller_owned_poll_lock_recovers_without_full_rollback(monkeypatch):
    """Lock during write → SAVEPOINT rollback → read-only fallback; marker row survives."""
    if get_db_backend() == "postgres":
        pytest.skip("unit simulation uses sqlite dialect helpers; PG covered by source guards")

    monkeypatch.setenv("GC_DB_BACKEND", "postgres")
    # Force backend read after env change — get_db_backend may cache.
    import game.db as db_mod

    monkeypatch.setattr(db_mod, "get_db_backend", lambda: "postgres")

    conn = _CallerOwnedConn()
    begin_write_transaction = lambda c: None  # noqa: E731 — already in TX

    player = {"id": 7, "metal": 1, "crystal": 2, "fuel_cells": 0}
    planet = {
        "id": 70,
        "metal": 1,
        "crystal": 2,
        "fuel_cells": 0,
        "last_update": 1.0,
    }

    monkeypatch.setattr(
        "game.planet_evolution.repository.get_context_planet",
        lambda uid, conn=None: planet,
    )
    monkeypatch.setattr("game.models.load_player", lambda uid, conn=None: dict(player))
    monkeypatch.setattr(
        "game.queue_poll.player_fleet_is_dirty",
        lambda uid, conn=None, now=None: False,
    )
    monkeypatch.setattr(
        "game.queue_poll.should_poll_attempt_queue_finish",
        lambda uid, conn=None, now=None, planet_id=None: (True, "test"),
    )
    monkeypatch.setattr(
        "game.queue_poll.try_claim_poll_due_finish",
        lambda uid, conn=None, now=None: True,
    )
    monkeypatch.setattr(
        "game.fleet_worker.is_fleet_worker_heartbeat_fresh",
        lambda conn=None, now=None: True,
    )

    def _finish(uid, conn, **kwargs):
        conn._fail_on_finish = True
        conn.execute("SELECT FINISH_INJECT")
        return {"derived_sync_count": 0}

    monkeypatch.setattr("game.queue_engine.finish_player_due_work", _finish)
    monkeypatch.setattr("game.db.begin_write_transaction", begin_write_transaction)
    monkeypatch.setattr("game.db.in_transaction", lambda c: True)

    # Preserve a pre-poll caller write marker outside the SAVEPOINT.
    conn.execute("UPDATE caller_marker SET v = 1")
    conn._marker_written = True
    marker_before = list(conn.statements)

    from game.logic import _read_player_live_state_no_writes

    def _ro(uid, conn, player, planet):
        # Prove connection still accepts SQL after soft-fail recovery.
        conn.execute("SELECT 1 AS gc_tx_ok")
        return (
            dict(player),
            {"metal_mine": 1},
            1.0,
            10,
            0,
            {"metal": 100},
        )

    monkeypatch.setattr("game.logic._read_player_live_state_no_writes", _ro)

    view, buildings, ratio, et, eu, caps = read_player_live_state_for_poll(7, conn=conn)

    assert int(view["id"]) == 7
    assert buildings["metal_mine"] == 1
    joined = "\n".join(conn.statements)
    assert "SAVEPOINT gc_poll_live_write" in joined
    assert "ROLLBACK TO SAVEPOINT gc_poll_live_write" in joined
    assert "UPDATE caller_marker SET v = 1" in marker_before
    # Full rollback of outer TX must not happen (caller marker statement stays).
    assert not any(s.upper().startswith("ROLLBACK") and "SAVEPOINT" not in s.upper() for s in conn.statements)
    assert not conn._aborted
    assert "SELECT 1 AS gc_tx_ok" in joined
