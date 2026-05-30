"""Scrapyard recycle tests."""

from __future__ import annotations

import importlib
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.fleet import add_planet_ships, get_planet_ships
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.scrapyard import recycle_ships, scrap_refund_ratio, scrap_value_for_ship


@pytest.fixture
def scrap_db(tmp_path, monkeypatch):
    db_path = tmp_path / "scrap.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_scrap_refund_in_range():
    for _ in range(20):
        r = scrap_refund_ratio()
        assert 0.50 <= r <= 0.75


def test_recycle_ships_refunds_and_deducts(scrap_db):
    ok, _, user = create_user(f"scrap_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        cur = conn.cursor()
        cur.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        planet_id = int(cur.fetchone()["id"])
        add_planet_ships(planet_id, uid, {"spark_drone": 3}, conn=conn)
        conn.commit()

        ok_r, reason, result = recycle_ships(
            player_id=uid,
            planet_id=planet_id,
            ship_key="spark_drone",
            amount=2,
            conn=conn,
        )
        assert ok_r, reason
        assert result
        assert int(get_planet_ships(planet_id, conn=conn).get("spark_drone", 0)) == 1
        preview = scrap_value_for_ship("spark_drone", 2, ratio=result["refund_ratio"])
        assert result["refund"]["metal"] == preview["metal"]
    finally:
        conn.close()
