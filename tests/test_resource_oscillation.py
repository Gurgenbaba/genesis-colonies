"""
GC-P0-RESOURCE-OSCILLATION: resources must not regress without spend actions.

Run: python -m pytest tests/test_resource_oscillation.py -v
"""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as dbmod
import game.logic as logic
import game.models as models
from game.models import create_user, get_homeworld, init_db, save_planet_buildings
from game.resources import project_planet_resource_balances, update_planet_resources


@pytest.fixture()
def resource_db(tmp_path, monkeypatch):
    db_file = tmp_path / "resource_osc.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()
    ok, err, user = create_user(f"res_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    planet = get_homeworld(player_id=uid)
    conn = models.db()
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ?, last_update = ? WHERE id = ?;",
        (500, 500, 10, time.time() - 45.0, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    save_planet_buildings(int(planet["id"]), {"metal_mine": 3, "crystal_mine": 2})
    return uid, dict(planet)


def test_stale_planet_row_tick_does_not_regress(resource_db):
    """Stale in-memory planet row must not overwrite fresher DB balances on tick."""
    uid, planet = resource_db
    planet_id = int(planet["id"])
    conn = models.db()
    try:
        row = conn.execute(
            "SELECT * FROM planets WHERE id = ? LIMIT 1;",
            (planet_id,),
        ).fetchone()
        stale_snapshot = dict(row)
        updated, _, _, _, _ = update_planet_resources(dict(row), conn=conn)
        conn.commit()
        metal_after_first = int(updated["metal"])
        assert metal_after_first >= int(stale_snapshot["metal"])

        updated2, _, _, _, _ = update_planet_resources(stale_snapshot, conn=conn)
        conn.commit()
        assert int(updated2["metal"]) >= metal_after_first
    finally:
        conn.close()


def test_elapsed_zero_does_not_lower_resources(resource_db):
    uid, planet = resource_db
    conn = models.db()
    try:
        now = time.time()
        conn.execute(
            "UPDATE planets SET metal = ?, last_update = ? WHERE id = ?;",
            (777, now, int(planet["id"])),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM planets WHERE id = ? LIMIT 1;",
            (int(planet["id"]),),
        ).fetchone()
        updated, _, _, _, _ = update_planet_resources(dict(row), conn=conn)
        conn.commit()
        assert int(updated["metal"]) >= 777
    finally:
        conn.close()


def test_poll_read_path_projects_accrual_without_persist(resource_db):
    uid, planet = resource_db
    conn = models.db()
    try:
        row = conn.execute(
            "SELECT * FROM planets WHERE id = ? LIMIT 1;",
            (int(planet["id"]),),
        ).fetchone()
        raw_metal = int(row["metal"])
        player = models.load_player(uid, conn=conn)
        projected = project_planet_resource_balances(dict(row), conn=conn)
        assert int(projected["metal"]) >= raw_metal

        player_view, _, _, _, _, _ = logic._read_player_live_state_no_writes(
            uid, conn, player, dict(row)
        )
        assert int(player_view["metal"]) >= raw_metal
        assert int(player_view["metal"]) >= int(projected["metal"])
    finally:
        conn.close()


def test_full_refresh_not_lower_than_diet_poll(resource_db):
    """Diet poll path must not report lower metal than authoritative full refresh."""
    uid, _ = resource_db
    conn = models.db()
    try:
        full_player, _, _, _, _, _ = logic.refresh_player_live_state(uid, conn=conn)
        full_metal = int(full_player["metal"])

        poll_player, _, _, _, _, _ = logic.read_player_live_state_for_poll(uid, conn=conn)
        poll_metal = int(poll_player["metal"])
        assert poll_metal >= full_metal
    finally:
        conn.close()


def test_attach_canonical_server_time_includes_state_version():
    payload = logic.attach_canonical_server_time({"ok": True})
    assert "state_version" in payload
    assert float(payload["state_version"]) >= float(payload["server_time"]) - 0.001
    assert payload["server_now"] == int(payload["server_time"])


def test_api_game_state_includes_state_version(tmp_path, monkeypatch):
    import os
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    db_file = tmp_path / "resource_api.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    result = subprocess.run(
        [sys.executable, str(root / "migrate.py")],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    init_db()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import importlib
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    ok, _, user = create_user(f"api_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok and user
    pid = int(user["id"])
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = pid
    r = client.get("/api/game-state")
    assert r.status_code == 200
    data = r.get_json()
    assert "state_version" in data
    assert float(data["state_version"]) > 0
