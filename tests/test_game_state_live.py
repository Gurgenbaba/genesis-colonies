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


def test_api_game_state_no_500_when_queue_finish_locked(game_client, monkeypatch):
    import sqlite3

    from game import queue_engine

    client, _pid = game_client

    def _locked(**_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(queue_engine, "finish_due_work_once", _locked)
    monkeypatch.setenv("GC_POLL_FINISH_INTERVAL_SEC", "0")

    r = client.get("/api/game-state")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert "player" in body


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

    planet = get_homeworld(player_id=pid)
    now = time.time()
    add_build_job(int(planet["id"]), "metal_mine", now - 120, now - 1)

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


def test_api_build_cancel_returns_fresh_queue_times(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    now = time.time()

    j1 = add_build_job(planet_id, "metal_mine", now - 10, now + 40)
    j2 = add_build_job(planet_id, "crystal_mine", now + 500, now + 600)

    r_cancel = client.post(
        "/api/buildings/cancel",
        json={"job_id": int(j1)},
        headers={"Content-Type": "application/json"},
    )
    assert r_cancel.status_code == 200
    body = r_cancel.get_json()
    assert body.get("ok") is True
    assert "state" in body
    bq = body["state"].get("build_queue") or {}
    queue = bq.get("queue") or []
    assert len(queue) == 1
    assert int(queue[0].get("remaining") or 0) > 0
    assert float(queue[0]["finish_time"]) > time.time()

    r_poll = client.get("/api/game-state")
    poll_queue = (r_poll.get_json().get("build_queue") or {}).get("queue") or []
    assert len(poll_queue) == 1
    assert int(poll_queue[0]["id"]) == int(queue[0]["id"])


def test_api_research_cancel_returns_fresh_queue_times(game_client):
    client, pid = game_client
    _set_buildings(pid, {"research_lab": 3, "metal_mine": 1})
    now = time.time()

    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "energy_tech", now - 10, now + 40),
    )
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "mining_tech", now + 500, now + 600),
    )
    conn.commit()
    job_rows = conn.execute(
        "SELECT id FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC;",
        (pid,),
    ).fetchall()
    conn.close()
    j1 = int(job_rows[0]["id"])

    r_cancel = client.post(
        "/api/research/cancel",
        json={"job_id": j1},
        headers={"Content-Type": "application/json"},
    )
    assert r_cancel.status_code == 200
    body = r_cancel.get_json()
    assert body.get("ok") is True
    rq = (body.get("state") or {}).get("research") or {}
    queue = rq.get("queue") or []
    assert len(queue) == 1
    assert float(queue[0]["start_at"]) <= time.time() + 3.0


def test_api_game_state_poll_is_lightweight(game_client):
    client, _pid = game_client
    r = client.get("/api/game-state")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert "player" in body
    assert "build_queue" in body
    assert "unread_messages_count" in body
    assert "player_stats" in body
    assert "online_now" in body["player_stats"]
    assert "total_players" in body["player_stats"]
    assert "buildings_panel" not in body
    assert "exchange" not in body
    assert "fuel_exchange" not in body
    assert "scrapyard" not in body
    assert "planet_teaser" not in body
    assert body.get("overview", {}).get("status") is None


def test_api_game_state_include_panel_has_buildings_panel(game_client):
    client, _pid = game_client
    r = client.get("/api/game-state?include_panel=1")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert isinstance(body.get("buildings_panel"), dict)
    assert body["buildings_panel"]


def test_api_buildings_upgrade_state_includes_panel_and_resources(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1})
    planet = get_homeworld(player_id=pid)
    metal_before = int(planet["metal"])

    r = client.post(
        "/api/buildings/upgrade",
        json={"building_type": "metal_mine", "request_id": f"gc801-{uuid.uuid4().hex}"},
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert "state" in body
    state = body["state"]
    assert isinstance(state.get("buildings_panel"), dict)
    metal_after = int((state.get("player") or {}).get("metal") or state.get("resources", {}).get("metal") or 0)
    if body.get("ok"):
        assert metal_after < metal_before


def test_api_game_state_include_panel_uses_full_live_refresh(game_client, monkeypatch):
    import game.logic as logic

    calls = {"poll": 0, "full": 0}
    orig_poll = logic.read_player_live_state_for_poll
    orig_full = logic.refresh_player_live_state

    def track_poll(*args, **kwargs):
        calls["poll"] += 1
        return orig_poll(*args, **kwargs)

    def track_full(*args, **kwargs):
        calls["full"] += 1
        return orig_full(*args, **kwargs)

    monkeypatch.setattr(logic, "read_player_live_state_for_poll", track_poll)
    monkeypatch.setattr(logic, "refresh_player_live_state", track_full)

    client, _pid = game_client
    client.get("/api/game-state")
    assert calls["poll"] >= 1
    poll_count = calls["poll"]
    full_before = calls["full"]

    client.get("/api/game-state?include_panel=1")
    assert calls["full"] > full_before
    assert calls["poll"] == poll_count


def test_api_game_state_buildings_panel_requirements_fields(game_client):
    """GC-546B: include_panel rows expose requirements for live client patch."""
    client, _pid = game_client
    r = client.get("/api/game-state?include_panel=1")
    assert r.status_code == 200
    panel = r.get_json().get("buildings_panel") or {}
    assert isinstance(panel, dict) and panel
    seen = 0
    for rows in panel.values():
        for row in rows or []:
            seen += 1
            assert "requirements_met" in row
            assert isinstance(row.get("requirements_items"), list)
            assert "can_afford" in row
            assert "key" in row
    assert seen > 0


def test_logic_live_timer_helpers():
    from game import logic

    ts = logic.live_server_timestamp()
    assert isinstance(ts, int) and ts > 0
    assert logic.game_state_panel_finish_source() == "game_state_panel"


def test_logic_normalize_queue_job_timer_fields():
    from game import logic

    ts = logic.live_server_timestamp()
    fields = logic.normalize_queue_job_timer_fields(
        finish_at=float(ts) + 120.9,
        remaining=120,
        is_active=True,
        next_finish_at=float(ts) + 30.4,
    )
    assert fields["finish_at"] == int(ts) + 120
    assert fields["finish_time"] == fields["finish_at"]
    assert fields["countdown_at"] == fields["finish_at"]
    assert fields["remaining_seconds"] == 120
    assert fields["next_countdown_at"] == int(ts) + 30


def test_api_game_state_research_queue_timer_fields(game_client):
    client, pid = game_client
    from game.models import save_planet_buildings, get_homeworld

    save_planet_buildings(int(get_homeworld(player_id=pid)["id"]), {"research_lab": 3, "metal_mine": 1})
    now = time.time()
    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "energy_tech", now - 10, now + 45.7),
    )
    conn.commit()
    conn.close()

    r = client.get("/api/game-state")
    assert r.status_code == 200
    research = r.get_json().get("research") or {}
    queue = research.get("queue") or []
    assert queue
    head = queue[0]
    assert int(head.get("finish_at") or 0) > int(now)
    assert head.get("finish_time") == head.get("finish_at")
    assert head.get("countdown_at") == head.get("finish_at")
    assert int(head.get("remaining_seconds") or 0) > 0


def test_main_js_gc541_server_time_fallback_chain():
    src = open("static/main.js", encoding="utf-8").read()
    timer_now = src.split("function getTimerServerNow()")[1].split("function queryTimerElements")[0]
    assert "GC.lastState?.server_time" in timer_now
    assert "GC.lastState?.server_now" in timer_now
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function gameStateIncludePanel")[0]
    assert "syncServerClockFromState(data)" in apply

