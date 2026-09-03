"""GC-TK-ATOMIC-DELIVERY-001 — TK debit/shift/delivery are one mutation."""

from __future__ import annotations

import time
import uuid

import pytest

from game.db import begin_write_transaction, commit, db
from game.models import add_build_job, create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet
from game.timekeeper import apply_timekeeper, credit, get_balance


@pytest.fixture
def tk_atomic_db(tmp_path, monkeypatch):
    db_path = tmp_path / "tk_atomic.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn) -> int:
    ok, err, user = create_user(f"tk_atomic_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="TkAtomic", conn=conn)
    return uid


def test_failed_post_boost_finish_rolls_back_shift_and_tk_even_if_outer_commits(
    tk_atomic_db, monkeypatch
):
    import game.timekeeper as tk

    conn = db()
    try:
        uid = _player(conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 300, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 600, "test", conn=conn)
        commit(conn)

        finish_before = float(
            conn.execute(
                "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY id LIMIT 1;",
                (pid,),
            ).fetchone()["finish_time"]
        )

        calls = 0

        def fake_finish(_conn, _uid, _pid):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"ok": True, "errors": []}
            return {
                "ok": False,
                "errors": ["shipyard planet=175: canceling statement due to lock timeout"],
            }

        monkeypatch.setattr(tk, "_finish_before_apply", fake_finish)

        begin_write_transaction(conn)
        ok, reason, payload = apply_timekeeper(
            uid,
            "build",
            planet_id=pid,
            seconds=600,
            mode="partial",
            conn=conn,
        )
        assert ok is False
        assert reason == "queue_finish_failed"
        assert "lock timeout" in " ".join(payload.get("errors") or [])

        # Deliberately commit the outer transaction: the service savepoint must
        # already have undone both the queue shift and any value mutation.
        commit(conn)

        assert get_balance(uid, conn=conn) == 600
        finish_after = float(
            conn.execute(
                "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY id LIMIT 1;",
                (pid,),
            ).fetchone()["finish_time"]
        )
        assert finish_after == pytest.approx(finish_before, abs=0.001)
    finally:
        conn.close()


def test_timekeeper_planet_scope_uses_canonical_lock_and_checks_finish_status():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    tk_src = (root / "game" / "timekeeper.py").read_text(encoding="utf-8")
    inv_src = (root / "game" / "inventory_use.py").read_text(encoding="utf-8")

    assert "lock_planet_for_update(conn, pid)" in tk_src
    assert 'return False, "queue_finish_failed"' in tk_src
    assert "_tk_savepoint_rollback(conn)" in tk_src
    assert "last_result: Dict[str, Any]" in inv_src
    assert "return last_result" in inv_src
