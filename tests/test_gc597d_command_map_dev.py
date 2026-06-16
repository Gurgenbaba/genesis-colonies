"""GC-597D — Command Map DEV PREVIEW flag and UI."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc597d_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    return db_file


def _run_migrate(db_path: Path) -> None:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    result = subprocess.run(
        [sys.executable, str(MIGRATE_SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    _run_migrate(temp_db)
    init_db()
    try:
        dbmod.db().close()
    except Exception:
        pass

    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def _login(client) -> int:
    uname = f"gc597d_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return int(user["id"])


def test_command_map_dev_mode_default_enabled(monkeypatch):
    monkeypatch.delenv("GC_COMMAND_MAP_DEV_MODE", raising=False)
    from game.config import is_command_map_dev_mode

    assert is_command_map_dev_mode() is True


def test_command_map_dev_mode_env_off(monkeypatch):
    monkeypatch.setenv("GC_COMMAND_MAP_DEV_MODE", "0")
    from game.config import is_command_map_dev_mode

    assert is_command_map_dev_mode() is False


def test_galaxy_command_map_renders_dev_preview_banner(app_client, monkeypatch):
    monkeypatch.setenv("GC_COMMAND_MAP_DEV_MODE", "1")
    _login(app_client)
    body = app_client.get("/galaxy?view=command_map").get_data(as_text=True)
    assert "gc-command-map-dev-banner" in body
    assert "gc-dev-preview-badge" in body


def test_galaxy_classic_view_no_dev_banner(app_client, monkeypatch):
    monkeypatch.setenv("GC_COMMAND_MAP_DEV_MODE", "1")
    _login(app_client)
    body = app_client.get("/galaxy?view=system&galaxy=1&system=1").get_data(as_text=True)
    assert "gc-command-map-dev-banner" not in body


def test_command_map_telemetry_api(app_client, monkeypatch):
    monkeypatch.setenv("GC_COMMAND_MAP_DEV_MODE", "1")
    _login(app_client)
    ok = app_client.post("/api/command-map/telemetry", json={"event": "map_open"})
    assert ok.status_code == 200
    assert ok.get_json()["ok"] is True

    bad = app_client.post("/api/command-map/telemetry", json={"event": "not_a_real_event"})
    assert bad.status_code == 400


def test_static_contract_dev_preview():
    main = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "logCommandMapTelemetry" in main
    assert "command_map_dev_mode" in (ROOT / "game/config.py").read_text(encoding="utf-8")
    sidebar = (ROOT / "templates/partials/sidebar.html").read_text(encoding="utf-8")
    assert "gc-dev-preview-badge" in sidebar
