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
    distribute_resources,
    get_fleet_slot_status,
    process_fleet_tick,
    send_fleet,
)
from game.resources import get_storage_capacity
from game.models import get_planet_buildings, get_research_levels
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


def _count_batches_and_movements(
    conn, player_id: int, *, batch_type: str = "collect_resources", mission_type: str = "collect"
) -> tuple[int, int]:
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM fleet_batches WHERE player_id = ? AND batch_type = ?;",
        (int(player_id), batch_type),
    )
    batches = int(cur.fetchone()["c"])
    cur.execute(
        """
        SELECT COUNT(*) AS c FROM fleet_movements
        WHERE player_id = ? AND mission_type = ? AND status IN ('outbound', 'returning', 'holding');
        """,
        (int(player_id), mission_type),
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


def test_distribute_happy_path_three_targets(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=50000, fuel_cells=50000)
    _seed_ships(hub, uid, {"mule_courier": 12}, conn=conn)
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_before = float(cur.fetchone()["metal"])
    conn.commit()

    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={"mule_courier": 9},
        resources_mode="equal",
        resources={"metal": 9000, "crystal": 3000, "fuel_cells": 0},
        conn=conn,
    )
    assert ok, reason
    assert len(payload["started"]) == 3
    assert payload["batch"]["batch_type"] == "distribute_resources"
    batch_id = int(payload["batch"]["id"])
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM fleet_movements WHERE parent_batch_id = ?;",
        (batch_id,),
    )
    assert int(cur.fetchone()["c"]) == 3
    for item in payload["started"]:
        cur.execute(
            "SELECT mission_type, origin_planet_id, resources_json, status FROM fleet_movements WHERE id = ?;",
            (int(item["fleet_id"]),),
        )
        row = dict(cur.fetchone())
        assert row["mission_type"] == "transport"
        assert int(row["origin_planet_id"]) == hub
        assert json.loads(row["resources_json"])["metal"] > 0
        assert row["status"] == "outbound"

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_after_send = float(cur.fetchone()["metal"])
    assert hub_after_send < hub_before
    conn.close()


def test_distribute_arrival_credits_target_empty_return(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=1)
    target = targets[0]
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=50000, crystal=20000, fuel_cells=20000)
    _fund_planet(cur, target, metal=100, crystal=50)
    _seed_ships(hub, uid, {"mule_courier": 2}, conn=conn)
    conn.commit()

    ok, _, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=[target],
        ships={"mule_courier": 1},
        resources_mode="equal",
        resources={"metal": 5000, "crystal": 0, "fuel_cells": 0},
        conn=conn,
    )
    assert ok
    fleet_id = int(payload["started"][0]["fleet_id"])
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (target,))
    target_before = int(cur.fetchone()["metal"])

    now = time.time()
    cur.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (now - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute(
        "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
        (fleet_id,),
    )
    mv = dict(cur.fetchone())
    assert mv["status"] == "returning"
    assert json.loads(mv["resources_json"]) in ({}, {"metal": 0, "crystal": 0, "fuel_cells": 0})

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (target,))
    assert int(cur.fetchone()["metal"]) > target_before

    cur.execute(
        "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
        (now - 1, fleet_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
    assert cur.fetchone()["status"] == "completed"
    conn.close()


def test_distribute_fleet_slots_full_no_batch(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=3)
    g, s, p = _planet_coords(targets[0], conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=500000, crystal=500000, fuel_cells=500000)
    _seed_ships(hub, uid, {"mule_courier": 30}, conn=conn)
    max_slots = get_fleet_slot_status(uid, conn=conn)["max"]
    for _ in range(max_slots):
        send_fleet(
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
    batches_before, mv_before = _count_batches_and_movements(
        conn, uid, batch_type="distribute_resources", mission_type="transport"
    )
    conn.commit()

    ok, reason, _ = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={"mule_courier": 6},
        resources_mode="equal",
        resources={"metal": 6000},
        conn=conn,
    )
    assert not ok
    assert reason == "fleet_slots_full"
    batches_after, mv_after = _count_batches_and_movements(
        conn, uid, batch_type="distribute_resources", mission_type="transport"
    )
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()


def test_distribute_no_cargo_no_batch(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    _seed_ships(hub, uid, {"falcon_interceptor": 5}, conn=conn)
    batches_before, mv_before = _count_batches_and_movements(
        conn, uid, batch_type="distribute_resources", mission_type="transport"
    )
    conn.commit()

    ok, reason, _ = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=targets,
        ships={"falcon_interceptor": 2},
        resources_mode="equal",
        resources={"metal": 1000},
        conn=conn,
    )
    assert not ok
    assert reason == "no_cargo_ships"
    batches_after, mv_after = _count_batches_and_movements(
        conn, uid, batch_type="distribute_resources", mission_type="transport"
    )
    assert batches_after == batches_before
    assert mv_after == mv_before
    conn.close()


def test_distribute_hub_in_targets_filtered(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    _fund_planet(conn.cursor(), hub, metal=50000, crystal=10000, fuel_cells=20000)
    _seed_ships(hub, uid, {"mule_courier": 6}, conn=conn)
    conn.commit()

    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=[hub, targets[0], targets[1]],
        ships={"mule_courier": 4},
        resources_mode="equal",
        resources={"metal": 4000},
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
    conn.close()


def test_distribute_storage_cap_clamps_and_leaves_surplus_on_hub(logistics_db):
    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=2)
    target = targets[0]
    cur = conn.cursor()
    _fund_planet(cur, hub, metal=100000, crystal=10000, fuel_cells=50000)
    buildings = get_planet_buildings(target, conn=conn)
    research = get_research_levels(user_id=uid, conn=conn)
    caps = get_storage_capacity(buildings, research=research)
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (max(0, int(caps["metal"]) - 500), max(0, int(caps["crystal"]) - 100), target),
    )
    _seed_ships(hub, uid, {"mule_courier": 4}, conn=conn)
    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_before = float(cur.fetchone()["metal"])
    conn.commit()

    ok, reason, payload = distribute_resources(
        player_id=uid,
        origin_planet_id=hub,
        target_planet_ids=[target],
        ships={"mule_courier": 2},
        resources_mode="equal",
        resources={"metal": 20000, "crystal": 2000, "fuel_cells": 0},
        conn=conn,
    )
    assert ok, reason
    delivered = payload["delivered_total"]
    assert delivered["metal"] <= 500
    assert delivered["metal"] > 0

    cur.execute("SELECT metal FROM planets WHERE id = ?;", (hub,))
    hub_after = float(cur.fetchone()["metal"])
    assert hub_before - hub_after == pytest.approx(delivered["metal"], rel=0, abs=1)
    assert hub_before - hub_after < 20000
    conn.close()


def test_distribute_api_returns_state(logistics_db):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    hub, targets = _hub_and_sources(uid, conn, sources=1)
    _fund_planet(conn.cursor(), hub, metal=50000, crystal=10000, fuel_cells=20000)
    _seed_ships(hub, uid, {"mule_courier": 3}, conn=conn)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post(
        "/api/fleet/logistics/distribute",
        json={
            "origin_planet_id": hub,
            "target_planet_ids": targets,
            "ships": {"mule_courier": 2},
            "resources": {"metal": 2000, "crystal": 500},
            "resources_mode": "equal",
            "request_id": str(uuid.uuid4()),
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body.get("state", {}).get("ok") is True
    assert body.get("data", {}).get("batch", {}).get("batch_type") == "distribute_resources"
