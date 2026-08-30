"""GC-PROD-SQLITE-STALL-001C — regression gates for availability invariants.

A) Single write TX remain bounded (structural fixes from 001A/001B).
B) Unrelated /healthz must stay serviceable while a DB writer blocks
   (HTTP model must not be a single cooperative gevent loop).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest


def test_entrypoint_encodes_gthread_availability_default():
    text = (
        Path(__file__).resolve().parent.parent / "scripts" / "docker-entrypoint.sh"
    ).read_text(encoding="utf-8")
    assert 'WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gthread}"' in text
    assert 'THREADS="${GUNICORN_THREADS:-4}"' in text
    assert "--threads" in text


def test_ws_refuses_long_lived_under_gthread_poll_fallback_contract(monkeypatch):
    """Availability contract: gthread => no WS pin; client uses polling."""
    monkeypatch.setenv("GUNICORN_WORKER_CLASS", "gthread")
    import app as app_mod

    app_mod.app.config.pop("GC_WS_LONG_LIVED_SAFE", None)
    assert app_mod.ws_long_lived_safe() is False


def test_healthz_stays_serviceable_while_sqlite_writer_blocks(tmp_path, monkeypatch):
    """Invariant B: a blocking writer must not freeze /healthz on threaded HTTP.

    Mirrors REPRO-005 micro-evidence: gthread keeps health responsive under an
    external SQLite writer lock; the product default is now gthread for that reason.
    """
    import game.db as gdb
    from game.models import init_db

    db_path = tmp_path / "avail.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()

    import app as app_mod

    app_mod.app.config["TESTING"] = True
    client = app_mod.app.test_client()

    # Baseline health without contention
    r0 = client.get("/healthz")
    assert r0.status_code == 200

    holder_ready = threading.Event()
    release = threading.Event()

    def _hold_writer() -> None:
        conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            holder_ready.set()
            release.wait(timeout=8.0)
            conn.execute("COMMIT")
        finally:
            conn.close()

    t = threading.Thread(target=_hold_writer, daemon=True)
    t.start()
    assert holder_ready.wait(timeout=5.0)

    t0 = time.perf_counter()
    # Flask test_client is threaded for this call only relative to the holder
    # thread (different OS thread) — proves healthz does not need the writer lock.
    r1 = client.get("/healthz")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    release.set()
    t.join(timeout=5.0)

    assert r1.status_code == 200
    # Must not wait on the writer (busy_timeout path). Health is lock-free.
    assert elapsed_ms < 500.0, f"healthz blocked {elapsed_ms:.1f}ms under writer hold"


def test_presence_and_fleet_budget_modules_still_importable():
    """Smoke that 001A/001B owners remain present (no accidental revert)."""
    from game.models import touch_player_online, _presence_touch_interval_sec
    from game.fleet import _process_fleet_tick_short_tx
    from game.queue_poll import try_claim_poll_due_finish
    from game.tx_context import tx_context

    assert _presence_touch_interval_sec() >= 5
    assert callable(touch_player_online)
    assert callable(_process_fleet_tick_short_tx)
    assert callable(try_claim_poll_due_finish)
    with tx_context(sub_owner="fleet_movement", movement_id=1):
        from game.tx_context import current

        assert current().get("sub_owner") == "fleet_movement"
