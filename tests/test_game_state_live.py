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
    app_module.app.config["TESTING"] = True

    uname = f"live_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    pid = int(user["id"])

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = pid
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

    # Bare /api/game-state is the lightweight poll path and diets "buildings"
    # out of the payload; include_panel=1 requests the full panel refresh
    # (GC-STABILIZE-002; app.py api_game_state / _is_game_state_poll_source).
    r1 = client.get("/api/game-state?include_panel=1")
    assert r1.status_code == 200
    data = r1.get_json()
    assert data["ok"] is True
    assert float(data["energy"]["mine_energy_factor"]) == pytest.approx(0.99, rel=0.01)
    assert int(data["energy"]["used"]) < used_before
    assert data["overview"]["energy_hint"] in ("ok", "low", "zero")
    assert int(data["buildings"]["metal_mine"]) >= 6


def test_api_game_state_overview_production_after_mining_tech(game_client):
    client, pid = game_client
    _set_buildings(pid, {"metal_mine": 5, "crystal_mine": 3, "solar_plant": 4})
    save_research_level("mining_tech", 0, pid)

    r0 = client.get("/api/game-state")
    assert r0.status_code == 200
    before = r0.get_json()
    prod_before = int(before["production_per_hour"]["metal_mine"])

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
    prod_after = int(data["production_per_hour"]["metal_mine"])
    assert prod_after > prod_before
    assert int(data["production_per_hour"]["metal_mine"]) == prod_after


def test_api_game_state_production_matches_gc820_formula(game_client):
    """Overview production_per_hour must match EffectResolver / production_formula."""
    from game.effects import get_effect_resolver
    from game.models import get_research_levels, save_research_level

    client, pid = game_client
    _set_buildings(
        pid,
        {"metal_mine": 12, "crystal_mine": 10, "fuel_cell_plant": 8, "solar_plant": 15},
    )
    save_research_level("mining_tech", 4, pid)

    r = client.get("/api/game-state")
    assert r.status_code == 200
    data = r.get_json()
    assert data.get("ok") is True

    planet = get_homeworld(player_id=pid)
    buildings = get_planet_buildings(int(planet["id"]))
    research = get_research_levels(pid)
    er = get_effect_resolver(pid, buildings=buildings, research=research, planet=planet)
    energy_total, energy_used = er.compute_energy()
    ratio = er.energy_ratio(energy_total, energy_used)
    expected = er.get_building_production_per_hour(ratio)

    assert int(data["production_per_hour"]["metal_mine"]) == expected["metal_mine"]
    assert int(data["production_per_hour"]["crystal_mine"]) == expected["crystal_mine"]
    assert int(data["production_per_hour"]["fuel_cell_plant"]) == expected["fuel_cell_plant"]


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
    assert status["production_per_hour"] == state["production_per_hour"]


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
    assert "buildings" not in body
    assert "codex" not in body
    assert "buildings_panel" not in body
    assert "exchange" not in body
    assert "fuel_exchange" not in body
    assert "scrapyard" not in body
    assert "planet_teaser" not in body
    assert body.get("overview", {}).get("status") is None
    assert "overview" in body
    assert "energy_hint" in body["overview"]
    assert "rows" not in body.get("overview", {})
    assert "active_fleets" in body
    assert "fleet_slots" in body
    assert "fleet_alerts" in body
    assert isinstance(body["fleet_alerts"], dict)
    assert body["fleet_alerts"]["has_incoming_attack"] is False
    assert isinstance(body["active_fleets"], dict)
    assert "items" in body["active_fleets"]
    assert "global_queue_hud" not in body


def test_api_game_state_poll_is_diet_gc747(game_client):
    """GC-747/GC-802: normal polls keep shell HUD slices, drop page-catalog blocks."""
    client, _pid = game_client
    body = client.get("/api/game-state").get_json()
    assert body.get("ok") is True
    research = body.get("research") or {}
    assert "techs" not in research
    assert "queue" in research
    assert "summary" in research
    assert "buildings" not in body
    assert "production_per_hour" in body
    assert isinstance(body.get("planets"), list)
    assert len(body["planets"]) >= 1
    pl = body.get("planet_limit") or {}
    assert pl.get("owned_worlds", pl.get("current", 0)) >= 1
    assert pl.get("max") is None or pl.get("max") >= 1
    assert "player_stats" not in body
    assert "building_queue" not in body
    assert "research_queue" not in body
    assert "planet_teaser" not in body
    assert "buildings" not in body
    assert "codex" not in body
    assert "imperial_directives" not in body
    assert "planet_relocation" not in body
    assert "exchange" not in body
    assert "scrapyard" not in body
    assert "buildings_panel" not in body
    assert "score" in body
    ap = body.get("active_planet") or {}
    assert ap.get("planet_id")
    assert "sidebar_nav" not in ap
    assert ap.get("empire_role_key") or ap.get("is_homeworld") is not None
    assert body.get("notification_revision")
    # GC-PERF-005 budget is compact wire size (~15KB via diet_payload_bytes), not
    # Flask pretty-print. Pretty-print grew past 16KB from intentional HUD slices
    # (commander / battle_pass / Threat Net keys) while compact stayed under budget.
    import json as _json

    compact = _json.dumps(body, separators=(",", ":"), default=str)
    assert len(compact.encode("utf-8")) < 15000, len(compact)

def test_api_game_state_include_panel_has_full_research_catalog(game_client):
    """Panel polls still include research.techs for live research/buildings pages."""
    client, _pid = game_client
    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    research = body.get("research") or {}
    assert isinstance(research.get("techs"), list)
    assert len(research["techs"]) > 0


def test_api_game_state_include_panel_has_heavy_hud_slices(game_client):
    """GC-740B: panel polls include fleet HUD, global queue HUD, and overview rows."""
    client, _pid = game_client
    r = client.get("/api/game-state?include_panel=1")
    assert r.status_code == 200
    body = r.get_json()
    assert body.get("ok") is True
    assert isinstance(body.get("overview", {}).get("rows"), list)
    assert len(body["overview"]["rows"]) > 0
    assert "active_fleets" in body
    assert isinstance(body["active_fleets"], dict)
    assert "items" in body["active_fleets"]
    assert "fleet_slots" in body
    assert "fleet_alerts" in body
    assert "global_queue_hud" in body
    assert isinstance(body["global_queue_hud"], dict)


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
    assert "buildings_panel" not in state
    delta = state.get("buildings_panel_delta") or {}
    assert isinstance(delta, dict) and delta
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


def test_build_queue_payload_includes_remaining_seconds():
    """GC-642: queue items expose canonical remaining_seconds for live header timers."""
    from game.buildings import get_build_queue_status_for_planet
    from game.models import create_user, get_homeworld, add_build_job, init_db

    init_db()
    uname = f"bq642_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    planet = get_homeworld(player_id=int(user["id"]))
    planet_id = int(planet["id"])
    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 10, now + 45.7)

    payload = get_build_queue_status_for_planet(planet_id, skip_finish=True)
    queue = payload.get("queue") or []
    assert queue
    head = queue[0]
    assert int(head.get("remaining_seconds") or 0) > 0
    assert head.get("remaining_seconds") == head.get("remaining")
    assert int(head.get("target_level") or 0) >= 1
    assert head.get("label_key")
    assert isinstance(payload.get("card_jobs_by_owner"), dict)


def test_global_queue_hud_payload_includes_jobs():
    """GC-643: lightweight game-state exposes unified queue HUD slice."""
    from game.live_state import global_queue_hud_for_game_state
    from game.models import create_user, get_homeworld, add_build_job, init_db

    init_db()
    uname = f"gqh643_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    planet = get_homeworld(player_id=int(user["id"]))
    planet_id = int(planet["id"])
    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 10, now + 45.7)

    from game.models import db

    conn = db()
    try:
        payload = global_queue_hud_for_game_state(int(user["id"]), conn=conn)
    finally:
        conn.close()

    assert isinstance(payload.get("jobs"), list)
    assert payload["jobs"]


def test_global_queue_hud_reuses_preloaded_queue(game_client, monkeypatch):
    """GC-741: panel HUD must not re-query build/research when caller already has them."""
    from game.buildings import get_build_queue_status_for_planet
    from game.live_state import global_queue_hud_for_game_state
    from game.models import db, get_homeworld, add_build_job
    from game.research import get_research_status

    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 10, now + 45.7)
    conn = db()
    try:
        build_queue = get_build_queue_status_for_planet(planet_id, conn=conn, skip_finish=True)
        research = get_research_status(user_id=pid, buildings={}, skip_finish=True, conn=conn)

        def fail_bq(*_args, **_kwargs):
            raise AssertionError("get_build_queue_status_for_planet should not run when build_queue is preloaded")

        def fail_rs(*_args, **_kwargs):
            raise AssertionError("get_research_status should not run when research is preloaded")

        monkeypatch.setattr("game.buildings.get_build_queue_status_for_planet", fail_bq)
        monkeypatch.setattr("game.research.get_research_status", fail_rs)
        payload = global_queue_hud_for_game_state(
            pid,
            conn=conn,
            planet=dict(planet),
            build_queue=build_queue,
            research=research,
            buildings={"metal_mine": 1, "crystal_mine": 1, "solar_plant": 1},
        )
    finally:
        conn.close()

    assert isinstance(payload.get("jobs"), list)
    head = payload["jobs"][0]
    assert head.get("owner_type") == "building"
    assert int(head.get("job_id") or 0) > 0
    assert int(head.get("remaining_seconds") or 0) > 0
    assert int(payload.get("planet_id") or 0) == planet_id


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


def test_game_state_account_safety_keeps_vacation_after_min_duration(game_client):
    """Mindestdauer abgelaufen = manuell deaktivierbar, nicht auto-aus."""
    client, pid = game_client
    conn = db()
    try:
        past = int(time.time()) - 60
        conn.execute(
            "UPDATE players SET vacation_mode_active = 1, vacation_locked_until = ? WHERE id = ?;",
            (past, pid),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/game-state")
    assert r.status_code == 200
    body = r.get_json()
    safety = body.get("account_safety") or {}
    assert safety.get("vacation_active") is True
    assert safety.get("vacation_can_disable") is True
    assert int(body.get("player_id") or 0) == pid


def test_api_include_panel_finishes_due_build_level(game_client):
    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    _set_buildings(pid, {"metal_mine": 4, "solar_plant": 2})
    now = time.time()
    add_build_job(planet_id, "metal_mine", now - 120, now - 1)

    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    assert int((body.get("buildings") or {}).get("metal_mine") or 0) == 5
    bq = body.get("build_queue") or {}
    metal_jobs = [
        j
        for j in (bq.get("queue") or [])
        if str(j.get("building_type") or j.get("building") or "") == "metal_mine"
    ]
    assert len(metal_jobs) == 0


def test_api_include_panel_finishes_due_ship_delivery(game_client):
    from game.shipyard import build_ship

    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (100_000, 100_000, planet_id),
    )
    cur.execute(
        """
        UPDATE planet_buildings
        SET orbital_shipyard = 1, research_lab = 10, command_center = 10, barracks = 10
        WHERE planet_id = ?;
        """,
        (planet_id,),
    )
    for tech in ("energy_tech", "mining_tech", "drone_tech", "engine_tech"):
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (pid, tech, 10),
        )
    conn.commit()
    ok, reason, _ = build_ship(
        player_id=pid, planet_id=planet_id, ship_key="mule_courier", amount=1, conn=conn
    )
    assert ok, reason
    cur.execute(
        "UPDATE shipyard_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, planet_id),
    )
    conn.commit()
    conn.close()

    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    sy = body.get("shipyard") or {}
    ships_block = sy.get("ships") or {}
    current = ships_block.get("current_ships") or {}
    assert int(current.get("mule_courier") or 0) >= 1


def test_api_include_panel_finishes_due_research_level(game_client):
    client, pid = game_client
    _set_buildings(pid, {"research_lab": 3, "solar_plant": 1})
    save_research_level("energy_tech", 7, pid)
    now = time.time()
    conn = db()
    conn.execute(
        "INSERT INTO research_queue (user_id, tech_key, start_at, finish_at) VALUES (?, ?, ?, ?);",
        (pid, "energy_tech", now - 60, now - 1),
    )
    conn.commit()
    conn.close()

    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    techs = (body.get("research") or {}).get("techs") or []
    energy = next((t for t in techs if t.get("key") == "energy_tech"), None)
    assert energy is not None
    assert int(energy.get("level") or 0) == 8


def test_api_notifications_summary_lightweight(game_client):
    client, _pid = game_client
    body = client.get("/api/notifications/summary").get_json()
    assert body.get("ok") is True
    assert "unread_messages_count" in body
    assert "latest_message_id" in body
    assert "fleet_alerts" in body
    assert "notification_revision" in body
    assert "buildings" not in body
    assert "build_queue" not in body
    assert "shipyard" not in body


def test_api_notifications_summary_unread_after_message(game_client):
    from game.messages import create_message

    client, pid = game_client
    conn = db()
    try:
        result = create_message(pid, "Live test", "Unread heartbeat", conn=conn)
        assert result.get("ok") is True
        conn.commit()
    finally:
        conn.close()

    body = client.get("/api/notifications/summary").get_json()
    assert body.get("ok") is True
    assert int(body.get("unread_messages_count") or 0) >= 1


def test_api_include_panel_finishes_due_troop_delivery(game_client):
    from game.models import save_planet_buildings
    from game.troops import enqueue_troop_train, get_planet_troops

    client, pid = game_client
    planet = get_homeworld(player_id=pid)
    planet_id = int(planet["id"])
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (100_000, 100_000, planet_id),
    )
    conn.commit()
    bld = get_planet_buildings(planet_id, conn=conn) or {}
    bld["barracks"] = 5
    save_planet_buildings(planet_id, bld, conn=conn)
    ok, reason, _ = enqueue_troop_train(
        player_id=pid,
        planet_id=planet_id,
        troop_key="militia",
        amount=2,
        conn=conn,
    )
    assert ok, reason
    cur.execute(
        "UPDATE troop_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, planet_id),
    )
    conn.commit()
    before = int(get_planet_troops(planet_id, conn=conn).get("militia") or 0)
    conn.close()

    body = client.get("/api/game-state?include_panel=1").get_json()
    assert body.get("ok") is True
    troops = (body.get("defense") or {}).get("troops") or {}
    assert isinstance(troops, dict)
    assert len(troops.get("queue") or []) == 0
    units = {u["key"]: u for u in (troops.get("units") or [])}
    assert int(units.get("militia", {}).get("amount") or 0) >= before + 2

def test_main_js_gc541_server_time_fallback_chain():
    src = open("static/main.js", encoding="utf-8").read()
    timer_now = src.split("function getTimerServerNow()")[1].split("function queryTimerElements")[0]
    assert "GC.lastState?.server_time" in timer_now
    assert "GC.lastState?.server_now" in timer_now
    apply = src.split("function applyGameStateData(data, _reason, opts)")[1].split("function refreshPageAfterQueueEvent")[0]
    assert "syncServerClockFromState(data)" in apply

