"""Global fleet worker — offline fleet processing (HTTP cron + request safety net)."""

from __future__ import annotations

import importlib
import json
import time
from unittest.mock import patch

import pytest

from game.db import db
from game.fleet import EXPEDITION_POSITION, add_planet_ships, send_fleet
from game.fleet_worker import (
    FLEET_WORKER_INTERVAL_SEC,
    FLEET_WORKER_KEY,
    any_due_fleet_movements,
    get_stage_skip_streak,
    _is_background_maintenance_source,
    _maybe_run_post_fleet_maintenance,
    run_fleet_worker,
)
from game.models import get_planets_by_player
from game.runtime_state import set_runtime_value
from tests.test_fleet import _force_outbound_arrival, _fund_planet, _player, _seed_ships

pytest_plugins = ("tests.test_fleet",)

FLEET_CRON_URL = "/api/internal/cron/fleet-tick"
RANKING_CRON_URL = "/api/internal/cron/ranking"
TOKEN = "test-fleet-worker-cron-token"


@pytest.fixture()
def fleet_worker_env(tmp_path, monkeypatch):
    db_file = tmp_path / "fleet_worker_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("GC_INTERNAL_CRON_TOKEN", TOKEN)
    monkeypatch.setenv("GC_FLEET_WORKER_INTERVAL_SEC", "120")
    monkeypatch.setenv("GC_EMBEDDED_CRON", "0")
    return db_file


@pytest.fixture()
def fleet_worker_client(fleet_worker_env, monkeypatch):
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import migrate

    migrate.main()
    import app as app_module

    importlib.reload(app_module)
    return app_module.app.test_client()


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


def _start_expedition(conn, uid: int, pid: int) -> int:
    coords = conn.execute("SELECT galaxy, system FROM planets WHERE id = ?;", (pid,)).fetchone()
    g, s = int(coords["galaxy"]), int(coords["system"])
    ok, reason, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=EXPEDITION_POSITION,
        mission_type="expedition",
        ships={"solar_skiff": 1},
        conn=conn,
    )
    assert ok, reason
    return int(result["fleet"]["id"])


def test_background_maintenance_source_gate():
    assert _is_background_maintenance_source("http_cron")
    assert _is_background_maintenance_source("cron")
    assert _is_background_maintenance_source("embedded_cron")
    assert _is_background_maintenance_source("game_worker")
    assert not _is_background_maintenance_source("overview")
    assert not _is_background_maintenance_source("game_state")


def test_post_fleet_maintenance_runs_on_embedded_cron(fleet_db, monkeypatch):
    """GC-2604: Railway embedded_cron must run pirate/inactive post-maint stages."""
    called = {"hof": False, "inactive": False}

    def fake_hof(**kw):
        called["hof"] = True
        return {"inserted": 0}

    def fake_inactive(conn, **kw):
        called["inactive"] = True
        return {"ok": True, "woke_count": 0, "enqueued": 0, "session_ticks": 0}

    monkeypatch.setattr("game.combat_hof.maybe_sync_combat_hof_incremental", fake_hof)
    monkeypatch.setattr(
        "game.combat_balance_bots.maybe_run_next_scheduled_scenario",
        lambda **kw: {"ok": True, "skipped": "disabled"},
    )
    monkeypatch.setattr(
        "game.world_boss.maybe_tick_world_boss_schedule",
        lambda **kw: {},
    )
    monkeypatch.setattr(
        "game.asteroids.maybe_tick_asteroid_schedule",
        lambda **kw: {},
    )
    monkeypatch.setattr(
        "game.pirates.bases.maybe_tick_pirate_bases",
        lambda **kw: {},
    )
    monkeypatch.setattr(
        "game.inactive_autoplay.maybe_tick_inactive_autoplay",
        fake_inactive,
    )
    monkeypatch.setattr(
        "game.combat.expire_due_debris_fields",
        lambda **kw: 0,
    )
    conn = db()
    _maybe_run_post_fleet_maintenance(conn, source="embedded_cron")
    assert called["hof"] is True
    assert called["inactive"] is True
    conn.close()


def test_post_fleet_maintenance_stage_order_inactive_before_pirates(fleet_db, monkeypatch):
    """GC-2610: inactive_autoplay must run before the costlier pirates stage."""
    order: list = []

    def fake_inactive(conn, **kw):
        order.append("inactive_autoplay")
        return {"ok": True, "woke_count": 0, "enqueued": 0, "session_ticks": 0}

    def fake_pirates(**kw):
        order.append("pirates")
        return {}

    monkeypatch.setattr("game.combat_hof.maybe_sync_combat_hof_incremental", lambda **kw: {"inserted": 0})
    monkeypatch.setattr(
        "game.combat_balance_bots.maybe_run_next_scheduled_scenario",
        lambda **kw: {"ok": True, "skipped": "disabled"},
    )
    monkeypatch.setattr("game.world_boss.maybe_tick_world_boss_schedule", lambda **kw: {})
    monkeypatch.setattr("game.asteroids.maybe_tick_asteroid_schedule", lambda **kw: {})
    monkeypatch.setattr("game.pirates.bases.maybe_tick_pirate_bases", fake_pirates)
    monkeypatch.setattr("game.inactive_autoplay.maybe_tick_inactive_autoplay", fake_inactive)
    monkeypatch.setattr("game.combat.expire_due_debris_fields", lambda **kw: 0)

    conn = db()
    _maybe_run_post_fleet_maintenance(conn, source="embedded_cron")
    conn.close()

    assert order == ["inactive_autoplay", "pirates"]


def test_post_fleet_maintenance_skip_streak_counters(fleet_db, monkeypatch):
    """GC-2610: budget skips increment a per-stage streak; a success resets it."""
    monkeypatch.setenv("GC_POST_FLEET_MAINTENANCE_BUDGET_SEC", "0")

    conn = db()
    try:
        assert get_stage_skip_streak("inactive_autoplay", conn=conn) == 0
        _maybe_run_post_fleet_maintenance(conn, source="embedded_cron")
        assert get_stage_skip_streak("inactive_autoplay", conn=conn) == 1
        _maybe_run_post_fleet_maintenance(conn, source="embedded_cron")
        assert get_stage_skip_streak("inactive_autoplay", conn=conn) == 2
    finally:
        conn.close()

    monkeypatch.setenv("GC_POST_FLEET_MAINTENANCE_BUDGET_SEC", "25")
    monkeypatch.setattr("game.combat_hof.maybe_sync_combat_hof_incremental", lambda **kw: {"inserted": 0})
    monkeypatch.setattr(
        "game.combat_balance_bots.maybe_run_next_scheduled_scenario",
        lambda **kw: {"ok": True, "skipped": "disabled"},
    )
    monkeypatch.setattr("game.world_boss.maybe_tick_world_boss_schedule", lambda **kw: {})
    monkeypatch.setattr("game.asteroids.maybe_tick_asteroid_schedule", lambda **kw: {})
    monkeypatch.setattr("game.pirates.bases.maybe_tick_pirate_bases", lambda **kw: {})
    monkeypatch.setattr(
        "game.inactive_autoplay.maybe_tick_inactive_autoplay",
        lambda conn, **kw: {"ok": True, "woke_count": 0, "enqueued": 0, "session_ticks": 0},
    )
    monkeypatch.setattr("game.combat.expire_due_debris_fields", lambda **kw: 0)

    conn = db()
    try:
        _maybe_run_post_fleet_maintenance(conn, source="embedded_cron")
        assert get_stage_skip_streak("inactive_autoplay", conn=conn) == 0
    finally:
        conn.close()


def test_post_fleet_maintenance_skipped_on_page_load(fleet_db, monkeypatch):
    called = {"hof": False, "bot": False}

    def fake_hof(**kw):
        called["hof"] = True
        return {"inserted": 0}

    def fake_bot(**kw):
        called["bot"] = True
        return {"ok": True, "skipped": "disabled"}

    monkeypatch.setattr("game.combat_hof.maybe_sync_combat_hof_incremental", fake_hof)
    monkeypatch.setattr(
        "game.combat_balance_bots.maybe_run_next_scheduled_scenario",
        fake_bot,
    )
    conn = db()
    _maybe_run_post_fleet_maintenance(conn, source="overview")
    assert called["hof"] is False
    assert called["bot"] is False
    conn.close()


def test_global_fleet_worker_processes_due_expedition(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    conn.commit()

    fleet_id = _start_expedition(conn, uid, pid)
    _force_outbound_arrival(conn, fleet_id)
    conn.commit()
    assert any_due_fleet_movements(conn=conn) is True

    result = run_fleet_worker(source="test", force=True, persist=False)
    assert result["ok"] is True
    assert int(result["processed_arrivals"]) == 1

    row = conn.execute(
        "SELECT status FROM fleet_movements WHERE id = ?;",
        (fleet_id,),
    ).fetchone()
    assert row["status"] == "holding"
    conn.close()


def test_global_fleet_worker_double_tick_idempotent(fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    conn.commit()

    fleet_id = _start_expedition(conn, uid, pid)
    _force_outbound_arrival(conn, fleet_id)
    conn.commit()

    first = run_fleet_worker(source="test", force=True, persist=False)
    second = run_fleet_worker(source="test", force=True, persist=False)
    assert int(first["processed_arrivals"]) == 1
    assert int(second["processed_arrivals"]) == 0
    conn.close()


def test_global_fleet_worker_interval_skip_when_idle(fleet_db):
    set_runtime_value(
        FLEET_WORKER_KEY,
        json.dumps(
            {
                "at": int(time.time()),
                "source": "test",
                "ok": True,
                "processed_arrivals": 0,
                "processed_returns": 0,
                "processed_holding": 0,
                "duration_ms": 1,
                "errors": [],
            }
        ),
    )
    result = run_fleet_worker(source="test", force=False, persist=False)
    assert result["skipped_interval"] is True
    assert int(result.get("next_run_in_sec") or 0) <= int(FLEET_WORKER_INTERVAL_SEC)


def test_internal_cron_fleet_tick_endpoint(fleet_worker_client, fleet_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    conn.commit()
    fleet_id = _start_expedition(conn, uid, pid)
    _force_outbound_arrival(conn, fleet_id)
    conn.commit()
    conn.close()

    resp = fleet_worker_client.post(FLEET_CRON_URL, headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert data.get("ok") is True
    assert int(data.get("processed_arrivals") or 0) >= 1


def test_ranking_cron_piggybacks_fleet_tick(fleet_worker_client):
    with patch("game.internal_cron.execute_fleet_tick") as mock_fleet:
        mock_fleet.return_value = {
            "ok": True,
            "skipped_interval": False,
            "processed_arrivals": 3,
            "processed_returns": 1,
            "processed_holding": 0,
            "duration_ms": 5,
            "errors": [],
        }
        with patch("game.internal_cron.run_ranking_worker") as mock_rank:
            mock_rank.return_value = {
                "ok": True,
                "skipped_interval": False,
                "players_updated": 1,
                "ranks_assigned": 1,
                "duration_ms": 10,
                "errors": [],
            }
            resp = fleet_worker_client.post(RANKING_CRON_URL, headers=_auth_headers())

    assert resp.status_code == 200
    data = resp.get_json()
    assert "fleet_tick" in data
    assert int(data["fleet_tick"]["processed_arrivals"]) == 3
    mock_fleet.assert_called_once_with(force=False, source="http_cron")
