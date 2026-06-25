"""
GC-ADMIN-PLANET-CAP-HARD — admin-only planet cap (no research unlock).

Run: python -m pytest tests/test_planet_cap_hard.py -v
"""

from __future__ import annotations

import uuid

import pytest

from game.admin_balance import save_balance_settings
from game.db import db
from game.logic import check_planet_cap_available, get_max_planets_per_player, get_planet_limit_block
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db, save_research_level
from game.planet_evolution.service import colonize_planet


@pytest.fixture
def cap_db(tmp_path, monkeypatch):
    db_path = tmp_path / "planet_cap.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb
    import game.models as models

    gdb._DB_PATH = None
    models.DB_PATH = str(db_path)
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"cap_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="CapTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _set_cap(value: int) -> None:
    settings, err = save_balance_settings({"max_colonies_per_player": int(value)})
    assert err is None, err
    assert settings is not None
    assert int(settings["max_colonies_per_player"]) == int(value)


def test_admin_setting_max_colonies_validated(cap_db):
    settings, err = save_balance_settings({"max_colonies_per_player": 2})
    assert err is None
    assert settings["max_colonies_per_player"] == 2

    _, err_low = save_balance_settings({"max_colonies_per_player": 0})
    assert err_low is not None

    _, err_high = save_balance_settings({"max_colonies_per_player": 51})
    assert err_high is not None


def test_planet_limit_block_uses_admin_setting(cap_db):
    uid = _player()
    _set_cap(2)
    conn = db()
    try:
        block = get_planet_limit_block(uid, conn=conn)
        assert block["current"] == 1
        assert block["max"] == 2
    finally:
        conn.close()


def test_colonize_allowed_below_cap_blocked_at_cap(cap_db):
    uid = _player()
    _set_cap(2)
    conn = db()
    try:
        ok1, reason1, extra1 = colonize_planet(
            uid,
            name="Colony Alpha",
            galaxy=1,
            system=120,
            position=3,
            conn=conn,
        )
        assert ok1, reason1
        assert extra1 and extra1.get("planet_id")

        block = get_planet_limit_block(uid, conn=conn)
        assert block["current"] == 2
        assert block["max"] == 2

        ok2, reason2, _ = colonize_planet(
            uid,
            name="Colony Beta",
            galaxy=1,
            system=121,
            position=4,
            conn=conn,
        )
        assert not ok2
        assert reason2 == "max_colonies_reached"
        assert len(get_planets_by_player(uid, conn=conn)) == 2
    finally:
        conn.close()


def test_high_research_does_not_raise_planet_cap(cap_db):
    uid = _player()
    _set_cap(2)
    conn = db()
    try:
        save_research_level("navigation_tech", 12, uid)
        save_research_level("mining_tech", 15, uid)
        save_research_level("storage_tech", 10, uid)
        conn.commit()
        assert get_max_planets_per_player(conn=conn) == 2
        block = get_planet_limit_block(uid, conn=conn)
        assert block["max"] == 2
    finally:
        conn.close()


def test_player_over_limit_not_deleted_but_blocked(cap_db):
    uid = _player()
    conn = db()
    try:
        for i in range(2):
            ok, reason, _ = colonize_planet(
                uid,
                name=f"Extra_{i}",
                galaxy=1,
                system=200 + i,
                position=1 + i,
                conn=conn,
            )
            assert ok, reason
        assert len(get_planets_by_player(uid, conn=conn)) == 3

        _set_cap(2)
        ok_cap, reason_cap = check_planet_cap_available(uid, conn=conn)
        assert not ok_cap
        assert reason_cap == "max_colonies_reached"

        block = get_planet_limit_block(uid, conn=conn)
        assert block["current"] == 3
        assert block["max"] == 2
        assert len(get_planets_by_player(uid, conn=conn)) == 3

        ok_new, reason_new, _ = colonize_planet(
            uid,
            name="Should Fail",
            galaxy=1,
            system=250,
            position=5,
            conn=conn,
        )
        assert not ok_new
        assert reason_new == "max_colonies_reached"
        assert len(get_planets_by_player(uid, conn=conn)) == 3
    finally:
        conn.close()


def test_universe_reset_does_not_change_planet_cap_setting(cap_db):
    from unittest.mock import patch

    from game.admin_universe_reset import default_reset_options, execute_universe_reset_keep_inventory

    _set_cap(2)
    _player()
    with patch("game.admin_universe_reset.create_pre_reset_backup", return_value="/tmp/fake-backup.sql"):
        result = execute_universe_reset_keep_inventory(reset_options=default_reset_options())
    assert result.get("action") == "universe_reset_keep_inventory"
    conn = db()
    try:
        row = conn.execute(
            "SELECT value FROM game_settings WHERE key = 'max_colonies_per_player';",
        ).fetchone()
        assert row is not None
        assert int(row["value"]) == 2
        assert get_max_planets_per_player(conn=conn) == 2
    finally:
        conn.close()
