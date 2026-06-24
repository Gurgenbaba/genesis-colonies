"""Shipyard build queue: timing, finish, cancel refund, reorder, fleet sync."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as gdb
from game.db import db
from game.fleet import get_planet_ships
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.shipyard import build_ship, cancel_shipyard_job, move_shipyard_job
from game.shipyard_queue import (
    MAX_SHIPYARD_QUEUE,
    finish_due_shipyard_jobs_for_planet,
    queue_count,
    shipyard_queue_for_client,
)


@pytest.fixture
def sy_queue_db(tmp_path, monkeypatch):
    db_path = tmp_path / "sy_queue.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    ok, err, user = create_user(f"syq_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _setup_shipyard(conn, uid, pid):
    from tests.test_shipyard import _grant_ship_test_prereqs

    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 5000 WHERE id = ?;",
        (pid,),
    )
    cur.execute(
        "UPDATE planet_buildings SET orbital_shipyard = 2 WHERE planet_id = ?;",
        (pid,),
    )
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()


def test_build_enqueues_not_instant_ships(sy_queue_db):
    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    ok, reason, result = build_ship(
        player_id=uid, planet_id=pid, ship_key="mule_courier", amount=2, conn=conn
    )
    assert ok, reason
    assert result["shipyard_queue"]["summary"]["count"] == 1
    ships = get_planet_ships(pid, conn=conn)
    assert ships.get("mule_courier", 0) == 0
    assert queue_count(pid, conn=conn) == 1
    conn.close()


def test_queue_full_rejects_fourth_job(sy_queue_db):
    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    for _ in range(MAX_SHIPYARD_QUEUE):
        ok, reason, _ = build_ship(
            player_id=uid, planet_id=pid, ship_key="spark_drone", amount=1, conn=conn
        )
        assert ok, reason
    ok4, reason4, _ = build_ship(
        player_id=uid, planet_id=pid, ship_key="spark_drone", amount=1, conn=conn
    )
    assert not ok4
    assert reason4 == "queue_full"
    conn.close()


def test_finish_delivers_ships_to_fleet_inventory(sy_queue_db):
    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    ok, _, _ = build_ship(
        player_id=uid, planet_id=pid, ship_key="mule_courier", amount=3, conn=conn
    )
    assert ok
    cur = conn.cursor()
    cur.execute(
        "UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, pid),
    )
    conn.commit()
    n = finish_due_shipyard_jobs_for_planet(conn, pid, uid, now=time.time())
    assert n == 1
    ships = get_planet_ships(pid, conn=conn)
    assert ships.get("mule_courier", 0) >= 3
    assert queue_count(pid, conn=conn) == 0
    conn.close()


def test_cancel_refunds_by_queue_state(sy_queue_db):
    from game.queue_refund import REFUND_RATIO_ACTIVE, refund_ratio_for_job

    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    cur = conn.cursor()
    before_m = float(cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"])
    ok, _, result = build_ship(
        player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn
    )
    assert ok
    after_build_m = float(cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"])
    spent = before_m - after_build_m
    job = result["shipyard_queue"]["queue"][0]
    job_id = int(job["id"])
    ratio = refund_ratio_for_job(
        start_time=float(job.get("start_at") or job.get("started_at") or time.time()),
        finish_time=float(job.get("finish_at") or time.time()),
        now=time.time(),
    )
    ok_c, _, _ = cancel_shipyard_job(player_id=uid, planet_id=pid, job_id=job_id, conn=conn)
    assert ok_c
    after_cancel_m = float(cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"])
    refunded = after_cancel_m - after_build_m
    assert ratio in (REFUND_RATIO_ACTIVE, 1.0)
    assert refunded == pytest.approx(spent * ratio, rel=0.01)
    conn.close()


def test_move_queue_reorders_finish_times(sy_queue_db):
    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    build_ship(player_id=uid, planet_id=pid, ship_key="spark_drone", amount=1, conn=conn)
    build_ship(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn)
    q1 = shipyard_queue_for_client(uid, pid, 2, conn=conn)["queue"]
    assert len(q1) == 2
    second_id = int(q1[1]["id"])
    ok, reason, payload = move_shipyard_job(
        player_id=uid, planet_id=pid, job_id=second_id, direction="up", conn=conn
    )
    assert ok, reason
    q2 = payload["shipyard_queue"]["queue"]
    assert q2[0]["ship_key"] == "mule_courier"
    conn.close()


def test_api_fleet_state_includes_completed_ships(sy_queue_db, monkeypatch):
    import app as app_mod

    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    build_ship(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=2, conn=conn)
    cur = conn.cursor()
    cur.execute(
        "UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, pid),
    )
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get(f"/api/fleet/state?planet_id={pid}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert data["data"]["ships"].get("mule_courier", 0) >= 2
    assert data["data"]["has_ships"] is True


def test_api_build_appends_queue_jobs(sy_queue_db):
    import app as app_mod

    conn = db()
    uid = _player()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r1 = client.post(
        "/api/shipyard/build",
        json={"ship_key": "spark_drone", "amount": 1, "planet_id": pid},
    )
    assert r1.status_code == 200
    d1 = r1.get_json()
    assert d1["ok"] is True
    assert d1["data"]["shipyard_queue"]["summary"]["count"] == 1

    r2 = client.post(
        "/api/shipyard/build",
        json={"ship_key": "mule_courier", "amount": 1, "planet_id": pid},
    )
    assert r2.status_code == 200
    d2 = r2.get_json()
    assert d2["ok"] is True
    assert d2["data"]["shipyard_queue"]["summary"]["count"] == 2
    keys = {j["ship_key"] for j in d2["data"]["shipyard_queue"]["queue"]}
    assert keys == {"spark_drone", "mule_courier"}

    conn = db()
    assert queue_count(pid, conn=conn) == 2
    conn.close()
