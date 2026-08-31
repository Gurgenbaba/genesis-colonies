"""Guards for PG lock soft-fail + initiation SAVEPOINT + schema cache."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_db_lock_error_covers_postgres_lock_timeout():
    source = (ROOT / "game" / "db.py").read_text(encoding="utf-8")
    assert "def is_db_lock_error" in source
    assert "LockNotAvailable" in source
    assert "canceling statement due to lock timeout" in source


def test_touch_player_online_uses_short_local_lock_timeout():
    source = (ROOT / "game" / "models.py").read_text(encoding="utf-8")
    assert "SET LOCAL lock_timeout = '250ms'" in source


def test_initiation_visit_uses_savepoint():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "SAVEPOINT gc_initiation_visit" in source
    assert "initiation page visit skipped (aborted TX)" in source


def test_postgres_table_exists_is_cached():
    source = (ROOT / "game" / "db_pg.py").read_text(encoding="utf-8")
    assert "_PG_TABLE_EXISTS_CACHE" in source


def test_galaxy_max_cached_and_list_system_passes_conn():
    source = (ROOT / "game" / "galaxy.py").read_text(encoding="utf-8")
    assert "_GALAXY_MAX_CACHE" in source
    assert "validate_coordinates(galaxy, system, POSITION_MIN, conn=conn)" in source
