"""Command Initiation Phase 1 — engine + event-bus fan-out."""

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


def test_pack_phase1_has_metal_mine_step():
    pack = load_pack()
    steps = flatten_steps(pack)
    assert steps
    first = steps[0]
    assert first["id"] == "build_metal_mines"
    assert first["target"] == 3
    assert first["filters"]["building_types"] == ["metal_mine"]
    assert first["route"] == "/buildings"


def test_resolve_step_route_highlights_ferronite_mine():
    from game.initiation.packs import resolve_step_route, step_at, step_image_path

    step = step_at(0)
    assert step
    href = resolve_step_route(step)
    assert href.startswith("/buildings?")
    assert "highlight=metal_mine" in href
    assert "tab=resources" in href
    assert step_image_path(step) == "img/buildings/metal_mine.png"


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

        # Crystal event should not have counted toward metal step (already advanced).
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
