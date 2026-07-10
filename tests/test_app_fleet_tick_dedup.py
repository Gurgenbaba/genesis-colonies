"""
Fleet tick deduplication — before_request must not double-run with page live context.

Run: python -m pytest tests/test_app_fleet_tick_dedup.py -v
"""

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
    db_file = tmp_path / "fleet_tick_dedup.db"
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
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _login(client, username: str, password: str = "test-pass-123") -> None:
    resp = client.post("/login", data={"username": username, "password": password}, follow_redirects=False)
    assert resp.status_code in (200, 302)


def test_maybe_run_global_fleet_tick_once_per_page_request(app_client, monkeypatch):
    calls: list[str] = []

    def _track(*, force=False, source="request"):
        calls.append(str(source))
        return {"ok": True, "skipped_interval": True}

    monkeypatch.setattr("game.fleet_worker.maybe_run_global_fleet_tick", _track)

    uname = f"fleet_dedup_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    _login(app_client, uname)
    resp = app_client.get("/research")
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0] == "research_view"


def test_fleet_tick_skipped_for_admin_balance_and_chat_poll(app_client, monkeypatch):
    calls: list[str] = []

    def _track(*, force=False, source="request"):
        calls.append(str(source))
        return {"ok": True, "skipped_interval": True}

    monkeypatch.setattr("game.fleet_worker.maybe_run_global_fleet_tick", _track)

    uname = f"fleet_skip_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123", is_admin=1)
    assert ok and user, err

    _login(app_client, uname)
    calls.clear()

    r = app_client.post("/api/admin/balance", json={"start_metal": 1000})
    assert r.status_code in (200, 400)
    assert calls == []

    calls.clear()
    r = app_client.get("/api/chat/bootstrap")
    assert r.status_code == 200
    assert calls == []

    calls.clear()
    r = app_client.get("/api/game-state")
    assert r.status_code == 200
    assert calls == []
