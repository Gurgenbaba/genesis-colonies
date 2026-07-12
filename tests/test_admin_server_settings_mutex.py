"""P0 — Admin server settings must not leak the SQLite write mutex."""

from __future__ import annotations

import importlib
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def admin_mutex_env(tmp_path, monkeypatch):
    db_file = tmp_path / "admin_mutex.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    return db_file


@pytest.fixture()
def admin_client(admin_mutex_env, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    env = __import__("os").environ.copy()
    env["GC_DB_PATH"] = str(admin_mutex_env)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    import app as app_module

    importlib.reload(app_module)
    from game.models import create_user, ensure_player_and_homeworld

    ok_a, _, admin_info = create_user(f"adm_{uuid.uuid4().hex[:8]}", "adminpass123", is_admin=1)
    assert ok_a
    ok_u, _, user_info = create_user(f"usr_{uuid.uuid4().hex[:8]}", "userpass123", is_admin=0)
    assert ok_u
    ensure_player_and_homeworld(int(user_info["id"]))

    client = app_module.app.test_client()
    return client, int(admin_info["id"]), int(user_info["id"])


def _as_admin(client, admin_id: int) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = int(admin_id)


def test_save_game_settings_releases_write_mutex(admin_mutex_env, monkeypatch):
    from game.bootstrap import bootstrap_application
    from game.db import write_mutex_depth
    from game.models import get_game_settings, init_db, save_game_settings

    bootstrap_application(skip_migration_check=True)
    init_db()

    assert write_mutex_depth() == 0
    save_game_settings({"universe_name": "Mutex Test Universe"})
    assert write_mutex_depth() == 0
    assert get_game_settings().get("universe_name") == "Mutex Test Universe"


def test_admin_server_save_then_game_state(admin_client):
    client, admin_id, user_id = admin_client
    from game.db import write_mutex_depth

    _as_admin(client, admin_id)
    assert write_mutex_depth() == 0

    save = client.post(
        "/api/admin/server",
        json={"universe_name": "Post-Save Universe", "motd_enabled": True},
    )
    assert save.status_code == 200
    payload = save.get_json()
    assert payload.get("ok") is True
    assert payload.get("settings", {}).get("universe_name") == "Post-Save Universe"
    assert write_mutex_depth() == 0

    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
    state = client.get("/api/game-state")
    assert state.status_code == 200
    assert state.get_json().get("ok") is True
    assert write_mutex_depth() == 0


def test_repeated_admin_server_saves_do_not_leak_mutex(admin_client):
    client, admin_id, _user_id = admin_client
    from game.db import write_mutex_depth

    _as_admin(client, admin_id)
    for i in range(20):
        res = client.post(
            "/api/admin/server",
            json={"universe_name": f"Universe {i}", "motd_enabled": bool(i % 2)},
        )
        assert res.status_code == 200
        assert res.get_json().get("ok") is True
        assert write_mutex_depth() == 0

    read_back = client.get("/api/admin/server")
    assert read_back.status_code == 200
    assert read_back.get_json().get("ok") is True
    assert write_mutex_depth() == 0


def test_admin_server_save_then_followup_writes(admin_client):
    """After admin save, further DB writes/reads must not block on a leaked mutex."""
    client, admin_id, user_id = admin_client
    from game.db import write_mutex_depth
    from game.models import get_game_settings, save_game_settings

    _as_admin(client, admin_id)
    save = client.post(
        "/api/admin/server",
        json={"universe_name": "Follow-up Write", "motd_enabled": True},
    )
    assert save.status_code == 200
    assert save.get_json().get("ok") is True
    assert write_mutex_depth() == 0

    assert get_game_settings().get("universe_name") == "Follow-up Write"
    save_game_settings({"motd_enabled": 0})
    assert write_mutex_depth() == 0

    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
    state = client.get("/api/game-state")
    assert state.status_code == 200
    assert state.get_json().get("ok") is True
    assert write_mutex_depth() == 0
