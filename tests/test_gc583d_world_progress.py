"""GC-583D — World location progression through expeditions."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.strategic_worlds import build_strategic_world_field
from game.planet_evolution.world_colonization import build_world_key, is_expedition_world_type
from game.planet_evolution.world_progress import (
    attach_world_location_progress,
    build_progress_payload,
    build_world_progress_map,
    default_progress_payload,
    familiarity_from_count,
    next_milestone_from_count,
    record_world_expedition_progress,
    world_progress_schema_ready,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc583d_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc583d.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def _create_player(conn):
    ok, err, user = create_user(f"prog_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Commander", conn=conn)
    return uid


def _expedition_field():
    for wx in range(500, 5000, 50):
        for wy in range(500, 5000, 50):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_expedition"):
                return field
    raise AssertionError("no expedition field")


def _salvage_field():
    for wx in range(500, 5000, 113):
        for wy in range(500, 5000, 97):
            field = build_strategic_world_field(float(wx), float(wy))
            if field.get("is_salvage"):
                return field
    raise AssertionError("no salvage field")


def test_world_progress_schema_ready(gc583d_db):
    from game.db import db

    conn = db()
    try:
        assert world_progress_schema_ready(conn=conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("count", "status", "next_ms"),
    [
        (0, "unknown", 1),
        (1, "mapped", 5),
        (4, "mapped", 5),
        (5, "stabilized", 10),
        (9, "stabilized", 10),
        (10, "outpost_prepared", None),
        (15, "outpost_prepared", None),
    ],
)
def test_milestone_payload(count, status, next_ms):
    payload = build_progress_payload(count)
    assert payload["expedition_count"] == count
    assert payload["familiarity_status"] == status
    assert payload["next_milestone"] == next_ms
    fam_status, label_key = familiarity_from_count(count)
    assert fam_status == status
    assert label_key == payload["familiarity_label_key"]
    assert next_milestone_from_count(count) == next_ms


def test_record_world_expedition_progress_increments(gc583d_db):
    field = _expedition_field()
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        conn.commit()
        wk = field["world_key"]
        for expected in (1, 2, 3):
            payload = record_world_expedition_progress(player_id, wk, conn=conn)
            assert payload["expedition_count"] == expected
        row = conn.execute(
            "SELECT expedition_count FROM world_progress WHERE player_id = ? AND world_key = ?;",
            (player_id, wk),
        ).fetchone()
        assert int(row["expedition_count"]) == 3
    finally:
        conn.close()


def test_record_ignores_salvage_world(gc583d_db):
    field = _salvage_field()
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        conn.commit()
        result = record_world_expedition_progress(player_id, field["world_key"], conn=conn)
        assert result is None
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM world_progress WHERE player_id = ?;",
            (player_id,),
        ).fetchone()["c"]
        assert int(count) == 0
    finally:
        conn.close()


def test_attach_world_location_progress_on_expedition_fields_only():
    expedition = _expedition_field()
    salvage = _salvage_field()
    expedition_node = dict(expedition)
    expedition_node["node_kind"] = "world_field"
    salvage_node = dict(salvage)
    salvage_node["node_kind"] = "world_field"
    progress_map = {
        expedition["world_key"]: build_progress_payload(5),
    }
    attach_world_location_progress([expedition_node, salvage_node], progress_map)
    assert expedition_node["expedition_count"] == 5
    assert expedition_node["familiarity_status"] == "stabilized"
    assert salvage_node.get("expedition_count", 0) == 0
    assert "familiarity_status" not in salvage_node or salvage_node.get("familiarity_status") is None


def test_attach_defaults_unknown_when_no_row():
    expedition = _expedition_field()
    node = dict(expedition)
    node["node_kind"] = "world_field"
    attach_world_location_progress([node], {})
    default = default_progress_payload()
    assert node["expedition_count"] == default["expedition_count"]
    assert node["familiarity_status"] == "unknown"


def test_world_progress_map_and_attach_integration(gc583d_db):
    field = _expedition_field()
    node = dict(field)
    node["node_kind"] = "world_field"
    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        wk = field["world_key"]
        record_world_expedition_progress(player_id, wk, conn=conn)
        conn.commit()
        progress_map = build_world_progress_map(player_id, conn=conn)
        assert progress_map[wk]["expedition_count"] == 1
        attach_world_location_progress([node], progress_map)
        assert node["familiarity_status"] == "mapped"
        assert node["next_milestone"] == 5
    finally:
        conn.close()


def test_fleet_world_expedition_increments_progress(gc583d_db):
    from game.db import db
    from game.fleet import add_planet_ships, process_fleet_tick, send_fleet

    field = _expedition_field()
    conn = db()
    try:
        player_id = _create_player(conn)
        pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
        conn.execute(
            "UPDATE planets SET metal = 50000, crystal = 50000, fuel_cells = 50000 WHERE id = ?;",
            (pid,),
        )
        add_planet_ships(pid, player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=1,
            target_system=1,
            target_position=1,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            world_key=field["world_key"],
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        # First tick only resolves outbound -> holding (expedition stays at the
        # destination for a holding period); world_progress is recorded when
        # holding -> returning resolves the outcome, so also fast-forward
        # holding_until and tick again (GC-STABILIZE-002; game/fleet.py process_fleet_tick).
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()
        conn.execute(
            "UPDATE fleet_movements SET holding_until = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        row = conn.execute(
            "SELECT expedition_count FROM world_progress WHERE player_id = ? AND world_key = ?;",
            (player_id, field["world_key"]),
        ).fetchone()
        assert row
        assert int(row["expedition_count"]) == 1
    finally:
        conn.close()


def test_classic_expedition_slot_does_not_increment_progress(gc583d_db):
    from game.db import db
    from game.fleet import EXPEDITION_POSITION, add_planet_ships, process_fleet_tick, send_fleet

    conn = db()
    try:
        player_id = _create_player(conn)
        pid = int(get_planets_by_player(player_id, conn=conn)[0]["id"])
        origin = conn.execute("SELECT * FROM planets WHERE id = ?;", (pid,)).fetchone()
        conn.execute(
            "UPDATE planets SET fuel_cells = 50000 WHERE id = ?;",
            (pid,),
        )
        add_planet_ships(pid, player_id, {"solar_skiff": 1}, conn=conn)
        conn.commit()

        ok, reason, result = send_fleet(
            player_id=player_id,
            origin_planet_id=pid,
            target_galaxy=int(origin["galaxy"]),
            target_system=int(origin["system"]),
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        conn.commit()
        process_fleet_tick(player_id=player_id, conn=conn)
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM world_progress WHERE player_id = ?;",
            (player_id,),
        ).fetchone()["c"]
        assert int(count) == 0
    finally:
        conn.close()


def test_inspector_template_has_progress_section(gc583d_db, monkeypatch):
    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    from game.db import db

    conn = db()
    try:
        player_id = _create_player(conn)
        conn.commit()
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id

    body = client.get("/galaxy?view=command_map&dev=1").get_data(as_text=True)
    assert "gc-world-inspector-modal" in body
    assert "data-world-field-inspect" in body
    assert "data-familiarity-label-key" in body
    assert "data-familiarity-status" in body


def test_progress_eligible_types_match_expedition_worlds():
    from game.planet_evolution.world_progress import progress_eligible_world_types

    for wt in progress_eligible_world_types():
        assert is_expedition_world_type(wt)
