"""GC-900B — multi-colony collect logistics (batch + mission collect)."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.fleet import (
    collect_resources,
    count_active_fleet_slots,
    get_fleet_slot_status,
    process_fleet_tick,
    send_fleet,
)
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.service import colonize_planet

from tests.test_fleet import _fund_planet, _planet_coords, _player, _second_colony, _seed_ships, fleet_db


@pytest.fixture
def logistics_db(tmp_path, monkeypatch):
    db_path = tmp_path / "logistics_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _hub_and_sources(uid: int, conn, *, sources: int = 2):
    hub = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    colony_ids = []
    for i in range(sources):
        pos = 5 + i
        ok, reason, extra = colonize_planet(
            uid, name=f"Colony {pos}", galaxy=1, system=300, position=pos, conn=conn
        )
        assert ok, reason
        cid = int(extra["planet_id"])
        _fund_planet(conn.cursor(), cid, metal=20000 + i * 1000, crystal=1000)
        colony_ids.append(cid)
    return hub, colony_ids


def _count_batches_and_movements(conn, player_id: int) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM fleet_batches WHERE player_id = ? AND batch_type = 'collect_resources';",
        (int(player_id),),
    )
    batches = int(cur.fetchone()["c"])
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM fleet_movements
        WHERE player_id = ? AND mission_type = 'collect' AND status IN ('outbound', 'returning', 'holding');
        """,
        (int(player_id),),
    )
    active_mv = int(cur.fetchone()["c"])
    return batches, active_mv


def test_qa_happy_path_three_sources_batch_and_return(logistics_db):
    """Manual QA Fall 1 — N movements, batch, slots, resources on hub after return."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    for cid in sources:
        _fund_planet(conn.cursor(), cid, metal=25000, crystal=3000)
    _seed_ships(hub, uid, {"mule_courier": 12}, conn=conn)
    slots_before = get_fleet_slot_status(uid, conn=conn)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={"mule_courier": 12},
        conn=conn,
    )
    assert ok, reason
    assert len(payload["started"]) == 3
    assert payload["batch"]["batch_type"] == "collect_resources"
    assert payload["batch"]["total_fleets"] == 3

    batch_id = int(payload["batch"]["id"])
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;",
        (batch_id,),
    )
    assert int(cur.fetchone()["c"]) == 3
    for item in payload["started"]:
        cur.execute(
            "SELECT mission_type, origin_planet_id, target_planet_id, status FROM fleet_movements WHERE id = ?;",
            (int(item["fleet_id"]),),
        )
        row = dict(cur.fetchone())
        assert row["mission_type"] == "collect"
        assert int(row["origin_planet_id"]) == hub
        assert int(row["target_planet_id"]) == int(item["source_planet_id"])
        assert row["status"] == "outbound"

    slots_after_send = get_fleet_slot_status(uid, conn=conn)
    assert slots_after_send["active"] == slots_before["active"] + 3

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_before = int(cur.fetchone()["metal"])
    now = time.time()
    for item in payload["started"]:
        fid = int(item["fleet_id"])
        cur.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (now - 1, fid),
        )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    for item in payload["started"]:
        fid = int(item["fleet_id"])
        cur.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (now - 1, fid),
        )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    assert int(cur.fetchone()["metal"]) > hub_before
    conn.close()


def test_qa_fleet_slots_full_no_partial_batch(logistics_db):
    """Manual QA Fall 2 — 3 sources, 0 free slots: no movements, no collect batch."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    g, s, p = _planet_coords(sources[0], conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {"mule_courier": 30}, conn=conn)
    max_slots = get_fleet_slot_status(uid, conn=conn)["max"]
    for _ in range(max_slots):
        ok, _, _ = send_fleet(
            player_id=uid,
            origin_planet_id=hub,
            target_galaxy=g,
            target_system=s,
            target_position=p,
            mission_type="transport",
            ships={"mule_courier": 1},
            resources={"metal": 1},
            conn=conn,
        )
        assert ok
    batches_before, mv_before = _count_batches_and_movements(conn, uid)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={"mule_courier": 6},
        conn=conn,
    )
    assert not ok
    assert reason == "fleet_slots_full"
    assert payload is None

    batches_after, mv_after = _count_batches_and_movements(conn, uid)
    assert batches_after == batches_before
    assert mv_after == mv_before
    assert count_active_fleet_slots(uid, conn=conn) == max_slots
    conn.close()


def test_qa_no_cargo_ships_no_batch(logistics_db):
    """Manual QA Fall 3 — combat-only selection leaves DB unchanged."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    _seed_ships(hub, uid, {"falcon_interceptor": 5}, conn=conn)
    batches_before, mv_before = _count_batches_and_movements(conn, uid)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={"falcon_interceptor": 2},
        conn=conn,
    )
    assert not ok
    assert reason == "no_cargo_ships"
    assert payload is None

    batches_after, mv_after = _count_batches_and_movements(conn, uid)
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()


def test_qa_hub_in_source_list_filtered(logistics_db):
    """Manual QA Fall 4 — hub in source_planet_ids is ignored, never collect hub→hub."""
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=2)
    _seed_ships(hub, uid, {"mule_courier": 6}, conn=conn)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[hub, sources[0], sources[1], hub],
        ships={"mule_courier": 4},
        conn=conn,
    )
    assert ok, reason
    assert len(payload["started"]) == 2
    cur = conn.cursor()
    for item in payload["started"]:
        cur.execute(
            "SELECT target_planet_id FROM fleet_movements WHERE id = ?;",
            (int(item["fleet_id"]),),
        )
        assert int(cur.fetchone()["target_planet_id"]) != hub

    ok2, reason2, _ = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[hub],
        ships={"mule_courier": 1},
        conn=conn,
    )
    assert not ok2
    assert reason2 == "no_planets"
    conn.close()


def test_collect_logistics_requires_cargo_ships(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _seed_ships(hub, uid, {"falcon_interceptor": 5}, conn=conn)
    conn.commit()

    ok, reason, _ = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={"falcon_interceptor": 2},
        conn=conn,
    )
    assert not ok
    assert reason == "no_cargo_ships"
    conn.close()


def test_collect_logistics_ship_split(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=3)
    _seed_ships(hub, uid, {"mule_courier": 30}, conn=conn)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=sources,
        ships={"mule_courier": 30},
        conn=conn,
    )
    assert ok, reason
    assert len(payload["started"]) == 3
    cur = conn.cursor()
    for item in payload["started"]:
        cur.execute(
            "SELECT ships_json FROM fleet_movements WHERE id = ?;",
            (int(item["fleet_id"]),),
        )
        ships = json.loads(cur.fetchone()["ships_json"])
        assert ships.get("mule_courier") == 10
    conn.close()


def test_collect_logistics_respects_fleet_slots(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    g, s, p = _planet_coords(source, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {"mule_courier": 20}, conn=conn)
    conn.commit()

    for _ in range(3):
        ok, reason, _ = send_fleet(
            player_id=uid,
            origin_planet_id=hub,
            target_galaxy=g,
            target_system=s,
            target_position=p,
            mission_type="transport",
            ships={"mule_courier": 1},
            resources={"metal": 1},
            conn=conn,
        )
        assert ok, reason
    conn.commit()

    ok, reason, _ = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[source],
        ships={"mule_courier": 2},
        conn=conn,
    )
    assert not ok
    assert reason == "fleet_slots_full"
    conn.close()


def test_collect_logistics_pickup_and_return(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    source = sources[0]
    _seed_ships(hub, uid, {"mule_courier": 2}, conn=conn)
    conn.commit()

    ok, reason, payload = collect_resources(
        player_id=uid,
        target_planet_id=hub,
        source_planet_ids=[source],
        ships={"mule_courier": 1},
        conn=conn,
    )
    assert ok, reason
    fleet_id = int(payload["started"][0]["fleet_id"])
    cur = conn.cursor()
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_before = int(cur.fetchone()["metal"])

    now = time.time()
    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (now - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute(
        "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
        (now - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_after = int(cur.fetchone()["metal"])
    assert hub_after > hub_before
    conn.close()


def test_logistics_page_renders_collect_form(logistics_db, monkeypatch):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    _second_colony(uid, conn=conn)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.get("/logistics")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "logistics-page" in html
    assert "logistics-collect-form" in html
    assert "logistics-tab-distribute" in html
    assert "logistics-collect-form" in html
    assert 'data-logistics-hub' in html


def test_collect_logistics_api_returns_state(logistics_db):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    hub, sources = _hub_and_sources(uid, conn, sources=1)
    _seed_ships(hub, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post(
        "/api/fleet/logistics/collect",
        json={
            "target_planet_id": hub,
            "source_planet_ids": sources,
            "ships": {"mule_courier": 2},
            "resources_mode": "all",
            "request_id": str(uuid.uuid4()),
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body.get("state", {}).get("ok") is True
    assert body.get("data", {}).get("batch", {}).get("batch_type") == "collect_resources"
