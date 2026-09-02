from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pg_pool_return_is_idempotent():
    src = (ROOT / "game/db_pg.py").read_text(encoding="utf-8")
    section = src.split("def connect_postgres()", 1)[1].split("def close_pool()", 1)[0]
    assert "returned = False" in section
    assert "if returned:" in section
    assert "pool.putconn(raw)" in section
    assert "wrapped.close = original_close" not in section


def test_request_pg_connections_are_tracked_and_drained():
    db_src = (ROOT / "game/db.py").read_text(encoding="utf-8")
    assert "def _track_request_postgres_connection" in db_src
    assert "gc_pg_request_connections" in db_src
    assert "_track_request_postgres_connection(conn)" in db_src
    assert "def close_request_postgres_connections" in db_src

    app_src = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "@app.teardown_request" in app_src
    assert "close_request_postgres_connections()" in app_src
