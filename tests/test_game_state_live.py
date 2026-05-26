"""
Flask /api/game-state live refresh tests.

Run: python -m pytest tests/test_game_state_live.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import db
from game.models import (
    add_build_job,
    create_user,
    get_homeworld,
    get_planet_buildings,
    init_db,
    save_research_level,
)
from game.queue_engine import finish_due_work

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def game_client(tmp_path, monkeypatch):
    db_file = tmp_path / "game_state_live.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
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

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)

    uname = f"live_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    pid = int(user["id"])

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, pid


def _set_buildings(player_id: int, levels: dict) -> None:
    from game.models import save_planet_buildings

    planet = get_homeworld(player_id=player_id)
    save_planet_buildings(int(planet["id"]), levels)


def test_api_game_state_energy_after_energy_tech_finish(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 6, "crystal_mine": 4, "solar_plant": 3})
    save_research_level("energy_tech", 0, pid)

    r0 = client.get("/api/game-state")
    assert r0.status_code == 200
    before = r0.get_json()
    used_before = int(before["energy"]["used"])

    conn = db()
    now = time.time()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "energy_tech", now - 60, now - 1),
    )
    conn.commit()
    conn.close()

    finish_due_work(player_id=pid, source="test_api")

    r1 = client.get("/api/game-state")
    assert r1.status_code == 200
    data = r1.get_json()
    assert data["ok"] is True
    assert float(data["energy"]["mine_energy_factor"]) == pytest.approx(0.95, rel=0.01)
    assert int(data["energy"]["used"]) < used_before
    assert data["overview"]["energy_hint"] in ("ok", "low", "zero")
    metal_row = next(r for r in data["overview"]["rows"] if r["key"] == "metal_mine")
    assert int(metal_row["level"]) >= 6


def test_api_game_state_overview_production_after_mining_tech(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 5, "crystal_mine": 3, "solar_plant": 4})
    save_research_level("mining_tech", 0, pid)

    r0 = client.get("/api/game-state")
    assert r0.status_code == 200
    before = r0.get_json()
    metal_before = next(r for r in before["overview"]["rows"] if r["key"] == "metal_mine")
    prod_before = int(metal_before["production_per_hour"])

    conn = db()
    now = time.time()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "mining_tech", now - 60, now - 1),
    )
    conn.commit()
    conn.close()

    finish_due_work(player_id=pid, source="test_mining")

    r1 = client.get("/api/game-state")
    assert r1.status_code == 200
    data = r1.get_json()
    metal_after = next(r for r in data["overview"]["rows"] if r["key"] == "metal_mine")
    prod_after = int(metal_after["production_per_hour"])
    assert prod_after > prod_before
    assert int(data["production_per_hour"]["metal_mine"]) == prod_after


def test_api_status_alias_matches_game_state(game_client):
    client, _pid = game_client
    r_state = client.get("/api/game-state")
    r_status = client.get("/api/status")
    assert r_state.status_code == 200
    assert r_status.status_code == 200
    state = r_state.get_json()
    status = r_status.get_json()
    assert state["ok"] is True
    assert status["ok"] is True
    assert status["energy"]["used"] == state["energy"]["used"]
    assert status["overview"]["rows"] == state["overview"]["rows"]


def test_api_game_state_single_finish_via_coerce(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "solar_plant": 1})

    from unittest.mock import patch

    from game.queue_engine import finish_due_work_once as real_finish

    calls: list[str] = []

    def counting(*args, **kwargs):
        calls.append("finish")
        return real_finish(*args, **kwargs)

    with patch("game.queue_engine.finish_due_work_once", side_effect=counting):
        r = client.get("/api/game-state")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        assert len(calls) == 1
