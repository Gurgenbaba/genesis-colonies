"""GC-800A — Recycler mission (debris harvest backend)."""

from __future__ import annotations

import time
import uuid

import pytest

from game import db as gdb
from game.combat import add_debris_field, get_debris_at_field, harvest_debris_at_field
from game.db import db
from game.fleet import (
    mission_allowed_for_target,
    process_fleet_tick,
    resolve_fleet_target,
    send_fleet,
)
from game.fleet_defs import MISSION_TYPES
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.fleet import add_planet_ships, get_planet_ships


@pytest.fixture
def recycler_db(tmp_path, monkeypatch):
    db_path = tmp_path / "recycler_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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
    ok, err, user = create_user(f"rec_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Recycler", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _seed_ships(planet_id: int, player_id: int, ships: dict, conn) -> None:
    add_planet_ships(planet_id, player_id, ships, conn=conn)


def _coords(planet_id: int, conn) -> tuple[int, int, int]:
    row = conn.execute(
        "SELECT galaxy, system, position FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    return int(row["galaxy"]), int(row["system"]), int(row["position"])


def test_recycle_mission_in_registry(recycler_db):
    assert "recycle" in MISSION_TYPES


def test_resolve_target_allows_recycle_when_debris_present(recycler_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _coords(pid, conn)
    add_debris_field(g, s, p, metal=5000, crystal=2000, conn=conn)
    conn.commit()
    target = resolve_fleet_target(uid, g, s, p, conn=conn)
    ok, reason = mission_allowed_for_target("recycle", target)
    assert ok, reason
    assert "recycle" in target["allowed_missions"]
    conn.close()


def test_recycle_requires_reclaimer_ship(recycler_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _coords(pid, conn)
    add_debris_field(g, s, p, metal=1000, crystal=0, conn=conn)
    conn.execute("UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 5000 WHERE id = ?;", (pid,))
    _seed_ships(pid, uid, {"mule_courier": 2}, conn)
    conn.commit()
    ok, reason, _ = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="recycle",
        ships={"mule_courier": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert not ok
    assert reason == "recycle_requires_reclaimer"
    conn.close()


def test_recycle_harvest_return_credits_origin(recycler_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, p = _coords(pid, conn)
    add_debris_field(g, s, p, metal=8000, crystal=3000, conn=conn)
    conn.execute(
        "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 10000 WHERE id = ?;",
        (pid,),
    )
    _seed_ships(pid, uid, {"harvest_reclaimer": 1}, conn)
    conn.commit()

    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="recycle",
        ships={"harvest_reclaimer": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert ok, reason
    movement_id = int(result["fleet"]["id"])
    conn.execute(
        "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
        (time.time() - 1, movement_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, now=time.time(), conn=conn)
    conn.commit()

    row = conn.execute(
        "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
        (movement_id,),
    ).fetchone()
    assert row["status"] == "returning"
    assert "8000" in str(row["resources_json"]) or "metal" in str(row["resources_json"])

    debris_after = get_debris_at_field(g, s, p, conn=conn)
    assert int(debris_after["metal"]) == 0
    assert int(debris_after["crystal"]) == 0

    conn.execute(
        "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
        (time.time() - 1, movement_id),
    )
    conn.commit()
    process_fleet_tick(player_id=uid, now=time.time(), conn=conn)
    conn.commit()

    metal = conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"]
    assert float(metal) >= 58000
    assert get_planet_ships(pid, conn=conn).get("harvest_reclaimer", 0) >= 1
    conn.close()


def test_main_js_recycle_ui_wired():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")
    assert "fleet_mission_recycle" not in src  # i18n keys only in locales
    assert 'mission=recycle' in open(
        Path(__file__).resolve().parents[1] / "templates/partials/galaxy_fleet_actions.html",
        encoding="utf-8",
    ).read()
    assert "syncMissionAllowlistFromTarget" in src
    assert 'mission === "recycle"' in src
    assert "formatDebrisPreview" in src


def test_harvest_debris_atomic(recycler_db):
    conn = db()
    add_debris_field(1, 100, 5, metal=1000, crystal=500, conn=conn)
    conn.commit()
    ok = harvest_debris_at_field(1, 100, 5, harvested={"metal": 400, "crystal": 200}, conn=conn)
    assert ok
    conn.commit()
    left = get_debris_at_field(1, 100, 5, conn=conn)
    assert left["metal"] == 600
    assert left["crystal"] == 300
    ok2 = harvest_debris_at_field(1, 100, 5, harvested={"metal": 9999, "crystal": 0}, conn=conn)
    assert not ok2
    conn.close()
