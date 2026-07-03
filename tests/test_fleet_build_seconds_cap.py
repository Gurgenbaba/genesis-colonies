"""Ship base build time cap — max 260s (4:20) per active hull."""

from __future__ import annotations

import math
import uuid

import pytest

from game.db import db
from game.fleet_defs import ACTIVE_SHIP_KEYS, MAX_SHIP_BUILD_SECONDS, SHIPS, get_ship
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.shipyard import unit_build_seconds


@pytest.fixture
def shipyard_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fleet_build_cap.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb

    gdb._DB_PATH = None
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
    ensure_player_and_homeworld(uid, player_name=f"P{uid}", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_active_ship_build_seconds_capped():
    for key in ACTIVE_SHIP_KEYS:
        assert int(SHIPS[key]["build_seconds"]) <= MAX_SHIP_BUILD_SECONDS, key


def test_deep_vault_ark_build_seconds_at_cap():
    spec = get_ship("deep_vault_ark")
    assert spec is not None
    assert int(spec["build_seconds"]) == MAX_SHIP_BUILD_SECONDS


def test_effective_build_seconds_minimum_one(shipyard_db, monkeypatch):
    monkeypatch.setattr("game.shipyard._shipyard_speed_multiplier", lambda **_: 1000.0)
    monkeypatch.setattr(
        "game.shipyard._directive_time_speed",
        lambda *args, **kwargs: 1000.0,
    )
    conn = db()
    try:
        uid = _player(conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        conn.execute("UPDATE planet_buildings SET orbital_shipyard = 10 WHERE planet_id = ?;", (pid,))
        conn.commit()
        unit = unit_build_seconds("spark_drone", 10, conn=conn, planet_id=pid)
        assert unit >= 1
        base = int(SHIPS["spark_drone"]["build_seconds"])
        raw = base * (0.975 ** 9) / 1000.0 / 1000.0
        assert unit == max(1, int(math.ceil(raw)))
    finally:
        conn.close()
