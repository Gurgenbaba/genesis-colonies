"""Command Initiation — efficient build-order tour (engine + visit + pack)."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.directives.progress import apply_directive_events, gameplay_event_delta
from game.initiation.engine import ensure_player_initiation
from game.initiation.packs import flatten_steps, load_pack, step_at
from game.initiation.pages import page_key_from_path, resolve_page_key
from game.initiation.progress import record_page_visit
from game.initiation.service import get_initiation_state, get_initiation_summary
from game.models import create_user

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


def test_pack_efficient_build_order_then_systems():
    pack = load_pack()
    assert int(pack.get("version") or 0) >= 3
    steps = flatten_steps(pack)
    assert steps
    first = steps[0]
    assert first["id"] == "solar_first"
    assert first["filters"]["building_types"] == ["solar_plant"]
    assert first["route"] == "/buildings"

    phase_ids = [p["id"] for p in pack.get("phases") or []]
    assert phase_ids == ["colony_core", "empire_expansion", "liveops_meta"]

    by_id = {s["id"]: s for s in steps}
    # Efficient economy path (GC-829 strategy).
    assert [s["id"] for s in steps[:8]] == [
        "solar_first",
        "metal_bootstrap",
        "crystal_gates",
        "solar_balance",
        "metal_lab_gate",
        "build_research_lab",
        "research_energy_tech",
        "build_fuel_cell",
    ]
    assert by_id["research_energy_tech"]["filters"]["research_keys"] == ["energy_tech"]
    assert by_id["research_mining_tech"]["filters"]["research_keys"] == ["mining_tech"]
    assert by_id["build_command_center"]["target"] == 2
    assert by_id["visit_galaxy"]["objective_key"] == "visit_page"
    assert by_id["visit_empire"]["route"] == "/empire"
    assert by_id["visit_referrals"]["filters"]["pages"] == ["referrals"]
    assert len(steps) >= 25


def test_resolve_step_route_highlights_solar_first():
    from game.initiation.packs import resolve_step_route, step_image_path

    step = step_at(0)
    assert step
    href = resolve_step_route(step)
    assert href.startswith("/buildings?")
    assert "highlight=solar_plant" in href
    assert "tab=resources" in href
    assert "solar" in step_image_path(step)


def test_page_key_mapping():
    assert page_key_from_path("/galaxy") == "galaxy"
    assert page_key_from_path("/galaxy?view=system") == "galaxy"
    assert page_key_from_path("/combat-simulator") == "combat_simulator"
    assert resolve_page_key(path="/empire", finish_source="page_load") == "empire"
    assert resolve_page_key(path="/buildings", finish_source="game_state") == ""
    assert resolve_page_key(path="/inventory", finish_source="inventory") == "inventory"


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
    # Empty filters still match any research (Directives / Story).
    assert (
        gameplay_event_delta(
            "complete_research",
            {"kind": "research_complete", "tech_key": "mining_tech", "amount": 1},
            filters={},
        )
        == 1
    )


def test_visit_page_objective_delta():
    assert (
        gameplay_event_delta(
            "visit_page",
            {"kind": "page_visit", "page": "galaxy", "amount": 1},
            filters={"pages": ["galaxy"]},
        )
        == 1
    )
    assert (
        gameplay_event_delta(
            "visit_page",
            {"kind": "page_visit", "page": "messages", "amount": 1},
            filters={"pages": ["galaxy"]},
        )
        == 0
    )


def test_initiation_solar_first_progress_and_advance(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
        state = get_initiation_state(pid, conn=conn)
        assert state["ready"]
        assert state["current"]["id"] == "solar_first"
        assert state["current"]["target"] == 1

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
        assert state["current"]["id"] == "metal_bootstrap"
        assert state["current"]["target"] == 2

        summary = get_initiation_summary(pid, conn=conn, ensure=False)
        assert summary["active"]
        assert summary["step_id"] == "metal_bootstrap"
        assert summary["route"].startswith("/buildings?")
        assert "highlight=metal_mine" in summary["route"]
        assert "tab=resources" in summary["route"]
    finally:
        conn.close()


def test_initiation_idempotent_source_event(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
        # Jump to a multi-target step so one event cannot finish the step alone.
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = 1, progress_value = 0, target_value = 2
            WHERE player_id = ?;
            """,
            (pid,),
        )
        eid = f"ini_dup:{uuid.uuid4().hex}"
        for _ in range(3):
            apply_directive_events(
                pid,
                [
                    {
                        "kind": "build_complete",
                        "building_type": "metal_mine",
                        "amount": 1,
                        "source_event_id": eid,
                    }
                ],
                conn=conn,
            )
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "metal_bootstrap"
        assert state["current"]["progress"] == 1
    finally:
        conn.close()


def test_visit_page_ignored_until_step_active(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
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
        ensure_player_initiation(pid, conn=conn)
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
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_galaxy"

        out = record_page_visit(pid, "galaxy", conn=conn)
        assert out["updated"] == 1
        assert out["completed"] == 1
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_planet_evolution"
    finally:
        conn.close()
