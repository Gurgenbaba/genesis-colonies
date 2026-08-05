"""Command Initiation — efficient build-order + existing-progress credit."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import commit, db
from game.directives.progress import apply_directive_events, gameplay_event_delta
from game.initiation.engine import credit_existing_progress, ensure_player_initiation
from game.initiation.packs import flatten_steps, load_pack, step_at
from game.initiation.pages import page_key_from_path, resolve_page_key
from game.initiation.progress import record_page_visit
from game.initiation.service import get_initiation_state, get_initiation_summary
from game.models import create_user, get_homeworld, save_planet_buildings

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def initiation_db(tmp_path, monkeypatch):
    db_file = tmp_path / "initiation.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
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
    yield db_file


def _create_player() -> int:
    ok, _reason, user = create_user(f"ini_{uuid.uuid4().hex[:8]}", "secret123")
    assert ok and user
    return int(user["id"])


def test_pack_level_thresholds_efficient_order():
    pack = load_pack()
    assert int(pack.get("version") or 0) >= 4
    steps = flatten_steps(pack)
    assert steps[0]["id"] == "solar_first"
    assert steps[0]["target"] == 3
    assert steps[0]["filters"]["building_types"] == ["solar_plant"]
    by_id = {s["id"]: s for s in steps}
    assert by_id["solar_balance"]["target"] == 4
    assert by_id["metal_grow"]["target"] == 5
    assert by_id["research_energy_tech"]["filters"]["research_keys"] == ["energy_tech"]


def test_resolve_step_route_highlights_solar_first():
    from game.initiation.packs import resolve_step_route, step_image_path

    step = step_at(0)
    assert step
    href = resolve_step_route(step)
    assert "highlight=solar_plant" in href
    assert "solar" in step_image_path(step)


def test_page_key_mapping():
    assert page_key_from_path("/galaxy") == "galaxy"
    assert resolve_page_key(path="/buildings", finish_source="game_state") == ""
    assert resolve_page_key(path="/galaxy", finish_source="page_load") == "galaxy"
    assert resolve_page_key(path="/ranking", finish_source="ranking") == "ranking"
    assert resolve_page_key(path="/messages", finish_source="messages") == "messages"
    assert resolve_page_key(path="/hall-of-fame", finish_source="hall_of_fame") == "hall_of_fame"
    assert resolve_page_key(path="/world-boss", finish_source="world_boss") == "world_boss"


def test_all_visit_page_pack_routes_resolve():
    """Every visit_page step must resolve its route → page key in filters."""
    for step in flatten_steps():
        if str(step.get("objective_key") or "") != "visit_page":
            continue
        filters = step.get("filters") if isinstance(step.get("filters"), dict) else {}
        pages = {str(x) for x in (filters.get("pages") or [])}
        assert pages, step.get("id")
        route = str(step.get("route") or "")
        assert page_key_from_path(route) in pages, (step.get("id"), route, pages)

def test_upgrade_buildings_respects_building_type_filter():
    assert (
        gameplay_event_delta(
            "upgrade_buildings",
            {"kind": "build_complete", "building_type": "solar_plant", "amount": 1},
            filters={"building_types": ["solar_plant"]},
        )
        == 1
    )
    assert (
        gameplay_event_delta(
            "upgrade_buildings",
            {"kind": "build_complete", "building_type": "metal_mine", "amount": 1},
            filters={"building_types": ["solar_plant"]},
        )
        == 0
    )


def test_complete_research_respects_research_key_filter():
    assert (
        gameplay_event_delta(
            "complete_research",
            {"kind": "research_complete", "tech_key": "energy_tech", "amount": 1},
            filters={"research_keys": ["energy_tech"]},
        )
        == 1
    )
    assert (
        gameplay_event_delta(
            "complete_research",
            {"kind": "research_complete", "tech_key": "mining_tech", "amount": 1},
            filters={"research_keys": ["energy_tech"]},
        )
        == 0
    )


def test_existing_solar_levels_are_credited(initiation_db):
    """Padre case: Solar already ≥3 → first task completes without rebuilding."""
    conn = db()
    try:
        pid = _create_player()
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(
            int(planet["id"]),
            {
                "solar_plant": 12,
                "metal_mine": 7,
                "crystal_mine": 5,
                "research_lab": 2,
                "fuel_cell_plant": 1,
                "command_center": 2,
                "orbital_shipyard": 1,
            },
            conn=conn,
        )
        commit(conn)

        ensure_player_initiation(pid, conn=conn)
        commit(conn)
        state = get_initiation_state(pid, conn=conn)
        assert state["ready"]
        # Building thresholds through shipyard should be skipped; fleet/visit remain.
        assert state["current"]["id"] in (
            "research_energy_tech",
            "research_mining_tech",
            "build_ship",
            "send_fleet",
            "visit_galaxy",
            "visit_planet_evolution",
        )
        assert state["current"]["id"] != "solar_first"
    finally:
        conn.close()


def test_credit_partial_solar_progress(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(int(planet["id"]), {"solar_plant": 2}, conn=conn)
        commit(conn)

        ensure_player_initiation(pid, conn=conn, credit=False)
        out = credit_existing_progress(pid, conn=conn)
        assert out["credited"] >= 1
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "solar_first"
        assert state["current"]["progress"] == 2
        assert state["current"]["target"] == 3
    finally:
        conn.close()


def test_initiation_solar_event_syncs_world_level(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
        planet = get_homeworld(player_id=pid)
        # Simulate completing Solar L1 via queue finish + event.
        save_planet_buildings(int(planet["id"]), {"solar_plant": 1}, conn=conn)
        commit(conn)
        apply_directive_events(
            pid,
            [
                {
                    "kind": "build_complete",
                    "building_type": "solar_plant",
                    "amount": 1,
                    "source_event_id": f"ini_solar:{uuid.uuid4().hex}",
                }
            ],
            conn=conn,
        )
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "solar_first"
        assert state["current"]["progress"] == 1
        assert state["current"]["target"] == 3
    finally:
        conn.close()


def test_initiation_idempotent_source_event(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        eid = f"ini_dup:{uuid.uuid4().hex}"
        planet = get_homeworld(player_id=pid)
        save_planet_buildings(int(planet["id"]), {"solar_plant": 1}, conn=conn)
        commit(conn)
        for _ in range(3):
            apply_directive_events(
                pid,
                [
                    {
                        "kind": "build_complete",
                        "building_type": "solar_plant",
                        "amount": 1,
                        "source_event_id": eid,
                    }
                ],
                conn=conn,
            )
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "solar_first"
        assert state["current"]["progress"] == 1
    finally:
        conn.close()


def test_visit_page_ignored_until_step_active(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        out = record_page_visit(pid, "galaxy", conn=conn)
        assert out["updated"] == 0
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "solar_first"
    finally:
        conn.close()


def test_visit_page_completes_when_active(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        steps = flatten_steps()
        galaxy_idx = next(i for i, s in enumerate(steps) if s["id"] == "visit_galaxy")
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = ?, progress_value = 0, target_value = 1
            WHERE player_id = ?;
            """,
            (galaxy_idx, pid),
        )
        out = record_page_visit(pid, "galaxy", conn=conn)
        assert out["updated"] == 1
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_planet_evolution"
    finally:
        conn.close()


def test_existing_fleet_movements_credit_send_step(initiation_db):
    """Veterans with prior fleet launches skip send_fleet without sending again."""
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        steps = flatten_steps()
        send_idx = next(i for i, s in enumerate(steps) if s["id"] == "send_fleet")
        planet = get_homeworld(player_id=pid)
        now = 1_700_000_000
        conn.execute(
            """
            INSERT INTO fleet_movements (
                player_id, origin_planet_id, target_galaxy, target_system, target_position,
                mission_type, ships_json, resources_json,
                departure_at, arrival_at, return_at, status, created_at, updated_at
            ) VALUES (?, ?, 1, 1, 1, 'transport', '{}', '{}', ?, ?, ?, 'outbound', ?, ?);
            """,
            (pid, int(planet["id"]), now, now + 60, now + 120, now, now),
        )
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = ?, progress_value = 0, target_value = 1, status = 'active'
            WHERE player_id = ?;
            """,
            (send_idx, pid),
        )
        commit(conn)
        out = credit_existing_progress(pid, conn=conn)
        assert out.get("completed") or out.get("credited")
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_galaxy"
    finally:
        conn.close()


def test_pjax_galaxy_visit_advances_initiation(initiation_db, monkeypatch):
    """Soft nav (X-PJAX) must credit visit_page — previously poll path skipped it."""
    import importlib

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")

    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        steps = flatten_steps()
        galaxy_idx = next(i for i, s in enumerate(steps) if s["id"] == "visit_galaxy")
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = ?, progress_value = 0, target_value = 1, status = 'active'
            WHERE player_id = ?;
            """,
            (galaxy_idx, pid),
        )
        commit(conn)
    finally:
        conn.close()

    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = pid

    resp = client.get("/galaxy", headers={"X-PJAX": "true"})
    assert resp.status_code == 200

    conn = db()
    try:
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_planet_evolution"
    finally:
        conn.close()


def test_pjax_messages_visit_advances_initiation(initiation_db, monkeypatch):
    import importlib

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")

    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn, credit=False)
        steps = flatten_steps()
        msg_idx = next(i for i, s in enumerate(steps) if s["id"] == "visit_messages")
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = ?, progress_value = 0, target_value = 1, status = 'active'
            WHERE player_id = ?;
            """,
            (msg_idx, pid),
        )
        commit(conn)
    finally:
        conn.close()

    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = pid

    resp = client.get("/messages", headers={"X-PJAX": "true"})
    assert resp.status_code == 200

    conn = db()
    try:
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_combat_simulator"
    finally:
        conn.close()
