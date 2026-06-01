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
        assert abs(result["refund"]["metal"] - preview["metal"]) <= 1
        conn.commit()
    finally:
        conn.close()

    verify = db()
    try:
        assert int(get_planet_ships(planet_id, conn=verify).get("spark_drone", 0)) == 1
    finally:
        verify.close()


def test_recycle_allows_storage_overflow(scrap_db):
    ok, _, user = create_user(f"scrap_ov_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        cur = conn.cursor()
        cur.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        planet_id = int(cur.fetchone()["id"])
        from game.models import get_planet_buildings, get_research_levels
        from game.resources import get_storage_capacity

        buildings = get_planet_buildings(planet_id, conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
        caps = get_storage_capacity(buildings, research=research)
        metal_cap = int(caps.get("metal") or 0)
        assert metal_cap > 0
        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
            (metal_cap, int(caps.get("crystal") or 0), planet_id),
        )
        add_planet_ships(planet_id, uid, {"spark_drone": 5}, conn=conn)
        conn.commit()

        ok_r, reason, result = recycle_ships(
            player_id=uid,
            planet_id=planet_id,
            ship_key="spark_drone",
            amount=3,
            conn=conn,
        )
        assert ok_r, reason
        assert result["refund"]["metal"] > 0

        cur.execute("SELECT metal FROM planets WHERE id = ?;", (planet_id,))
        metal_after = int(cur.fetchone()["metal"])
        assert metal_after > metal_cap
        conn.commit()
    finally:
        conn.close()


def test_scrapyard_api_persists_recycle(scrap_db, tmp_path, monkeypatch):
    import importlib
    import os

    import app as app_module

    db_path = os.environ.get("GC_DB_PATH")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as dbmod
    import game.models as models

    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    importlib.reload(app_module)

    conn = db()
    ok, err, user = create_user(f"scrap_api_{os.getpid()}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(conn.execute("SELECT id FROM planets WHERE player_id = ? LIMIT 1;", (uid,)).fetchone()["id"])
    add_planet_ships(planet_id, uid, {"spark_drone": 3}, conn=conn)
    conn.commit()
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    res = client.post(
        "/api/trader/scrapyard",
        json={"ship_key": "spark_drone", "amount": 1},
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["state"]["scrapyard"]["ships"]
    nomad_row = next(r for r in data["state"]["scrapyard"]["ships"] if r["ship_key"] == "spark_drone")
    assert int(nomad_row["amount"]) == 2

    conn2 = db()
    try:
        assert int(get_planet_ships(planet_id, conn=conn2).get("spark_drone", 0)) == 2
    finally:
        conn2.close()
