"""Command Initiation — full-game do-first tour (engine + visit + pack)."""

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
from game.initiation.packs import flatten_steps, load_pack
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


def test_pack_covers_three_phases_and_core_actions():
    pack = load_pack()
    assert int(pack.get("version") or 0) >= 2
    steps = flatten_steps(pack)
    assert steps
    first = steps[0]
    assert first["id"] == "build_metal_mines"
    assert first["target"] == 3
    assert first["filters"]["building_types"] == ["metal_mine"]
    assert first["route"] == "/buildings"

    phase_ids = [p["id"] for p in pack.get("phases") or []]
    assert phase_ids == ["colony_core", "empire_expansion", "liveops_meta"]

    by_id = {s["id"]: s for s in steps}
    assert by_id["visit_galaxy"]["objective_key"] == "visit_page"
    assert by_id["visit_galaxy"]["filters"]["pages"] == ["galaxy"]
    assert by_id["visit_empire"]["route"] == "/empire"
    assert by_id["visit_referrals"]["filters"]["pages"] == ["referrals"]
    assert len(steps) >= 25


def test_resolve_step_route_highlights_ferronite_mine():
    from game.initiation.packs import resolve_step_route, step_at, step_image_path

    step = step_at(0)
    assert step
    href = resolve_step_route(step)
    assert href.startswith("/buildings?")
    assert "highlight=metal_mine" in href
    assert "tab=resources" in href
    assert step_image_path(step) == "img/buildings/metal_mine.png"


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
            {"kind": "build_complete", "building_type": "metal_mine", "amount": 1},
            filters={"building_types": ["metal_mine"]},
        )
        == 1
    )
    assert (
        gameplay_event_delta(
            "upgrade_buildings",
            {"kind": "build_complete", "building_type": "crystal_mine", "amount": 1},
            filters={"building_types": ["metal_mine"]},
        )
        == 0
    )
    # Empty filters still match any build (Story / Directives).
    assert (
        gameplay_event_delta(
            "upgrade_buildings",
            {"kind": "build_complete", "building_type": "crystal_mine", "amount": 1},
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


def test_initiation_metal_mines_progress_and_advance(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
        state = get_initiation_state(pid, conn=conn)
        assert state["ready"]
        assert state["current"]["id"] == "build_metal_mines"
        assert state["current"]["target"] == 3

        for i in range(3):
            apply_directive_events(
                pid,
                [
                    {
                        "kind": "build_complete",
                        "building_type": "metal_mine",
                        "amount": 1,
                        "source_event_id": f"ini_metal:{i}:{uuid.uuid4().hex}",
                    }
                ],
                conn=conn,
            )

        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "build_crystal_mine"
        assert state["current"]["progress"] == 0

        summary = get_initiation_summary(pid, conn=conn, ensure=False)
        assert summary["active"]
        assert summary["step_id"] == "build_crystal_mine"
        assert summary["route"].startswith("/buildings?")
        assert "highlight=crystal_mine" in summary["route"]
        assert "tab=resources" in summary["route"]
    finally:
        conn.close()


def test_initiation_idempotent_source_event(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
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
        assert state["current"]["id"] == "build_metal_mines"
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
        assert state["current"]["id"] == "build_metal_mines"
    finally:
        conn.close()


def test_visit_page_completes_when_active(initiation_db):
    conn = db()
    try:
        pid = _create_player()
        ensure_player_initiation(pid, conn=conn)
        conn.execute(
            """
            UPDATE player_initiation
            SET step_index = 7, progress_value = 0, target_value = 1
            WHERE player_id = ?;
            """,
            (pid,),
        )
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_galaxy"

        out = record_page_visit(pid, "galaxy", conn=conn)
        assert out["updated"] == 1
        assert out["completed"] == 1
        state = get_initiation_state(pid, conn=conn)
        assert state["current"]["id"] == "visit_messages"
    finally:
        conn.close()
