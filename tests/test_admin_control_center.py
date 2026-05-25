"""
Admin Control Center API tests.

Run: python -m pytest tests/test_admin_control_center.py -v
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def admin_env(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


@pytest.fixture()
def app_client(admin_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)

    import importlib
    import app as app_module

    importlib.reload(app_module)

    from game.models import create_user, db, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user("admin_cc", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user("normal_cc", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_api_admin_requires_login(app_client):
    client, _, _ = app_client
    r = client.get("/api/admin/health")
    assert r.status_code == 401
    data = r.get_json()
    assert data["ok"] is False
    assert data["error"] == "not_logged_in"


def test_api_admin_forbidden_for_normal_user(app_client):
    client, _, _ = app_client
    _login(client, "normal_cc", "userpass123")
    r = client.get("/api/admin/health")
    assert r.status_code == 403
    assert r.get_json()["error"] == "forbidden"


def test_api_admin_health_ok_for_admin(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/api/admin/health")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert "health" in data
    assert "checks" in data["health"]


def test_player_search_works(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get(f"/api/admin/players?q={user_id}")
    assert r.status_code == 200
    players = r.get_json()["players"]
    assert any(int(p["id"]) == user_id for p in players)


def test_resources_set_clamps_negative(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{user_id}/resources",
        json={"mode": "set", "metal": -5000, "crystal": -100},
    )
    assert r.status_code == 200
    hw = r.get_json()["homeworld"]
    assert float(hw["metal"]) >= 0
    assert float(hw["crystal"]) >= 0


def test_queue_cancel_writes_audit_log(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")

    from game.models import db, get_homeworld
    import time

    hw = get_homeworld(user_id)
    planet_id = int(hw["id"])
    conn = db()
    conn.execute(
        "INSERT INTO build_queue (planet_id, building_type, start_time, finish_time) VALUES (?, ?, ?, ?);",
        (planet_id, "metal_mine", time.time(), time.time() + 3600),
    )
    conn.commit()
    job_id = conn.execute("SELECT id FROM build_queue ORDER BY id DESC LIMIT 1;").fetchone()["id"]
    conn.close()

    r = client.post(f"/api/admin/queue/build/{job_id}/cancel", json={})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True

    audit = client.get("/api/admin/audit-log?action=queue_cancel")
    assert audit.status_code == 200
    entries = audit.get_json()["entries"]
    assert any(e["action"] == "queue_cancel" for e in entries)


def test_destructive_action_without_confirm_rejected(app_client):
    client, admin_id, user_id = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.post(
        f"/api/admin/player/{user_id}/ban",
        json={"reason": "test", "hours": 1},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "confirm_required"


def test_audit_log_admin_only(app_client):
    client, _, _ = app_client
    _login(client, "normal_cc", "userpass123")
    r = client.get("/api/admin/audit-log")
    assert r.status_code == 403


def test_search_no_sql_injection(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    payload = "' OR 1=1; DROP TABLE users; --"
    r = client.get(f"/api/admin/players?q={payload}")
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert isinstance(data["players"], list)

    conn_ok = True
    try:
        from game.models import db

        conn = db()
        conn.execute("SELECT 1 FROM users LIMIT 1;")
        conn.close()
    except Exception:
        conn_ok = False
    assert conn_ok is True


def test_migrations_endpoint(app_client):
    client, _, _ = app_client
    _login(client, "admin_cc", "adminpass123")
    r = client.get("/api/admin/migrations")
    assert r.status_code == 200
    m = r.get_json()["migrations"]
    assert "applied" in m
    assert "pending" in m
