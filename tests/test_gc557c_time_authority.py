"""GC-557C — Single time authority + fleet dirty tick + origin scope."""

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
from game.fleet_origin import resolve_fleet_origin_planet_id
from game.logic import attach_canonical_server_time, live_server_timestamp
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.service import colonize_planet
from game.queue_poll import player_fleet_is_dirty

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def gc557c_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc557c.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
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

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_file


def test_attach_canonical_server_time():
    payload = attach_canonical_server_time({"ok": True})
    assert payload["server_now"] == int(payload["server_time"])
    assert "state_version" in payload
    assert float(payload["state_version"]) >= float(payload["server_time"]) - 0.001
    assert abs(payload["server_now"] - live_server_timestamp()) <= 1


def test_player_fleet_is_dirty_false_without_movements(gc557c_db):
    from game.db import db

    conn = db()
    try:
        ok, err, user = create_user(f"gc557c_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Cmd", conn=conn)
        assert player_fleet_is_dirty(uid, conn=conn) is False
    finally:
        conn.close()


def test_fleet_origin_scope_mismatch_logs(caplog, gc557c_db):
    from game.db import db
    from game.planet_evolution.repository import get_context_planet

    conn = db()
    try:
        ok, err, user = create_user(f"gc557c_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Cmd", conn=conn)
        colonize_planet(uid, name="Colony B", galaxy=1, system=400, position=3, conn=conn)
        context = get_context_planet(uid, conn=conn)
        colony = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? AND is_homeworld = 0 LIMIT 1;",
            (uid,),
        ).fetchone()
        colony_id = int(colony["id"])
        with caplog.at_level("WARNING"):
            resolved, audit = resolve_fleet_origin_planet_id(
                uid,
                colony_id,
                conn=conn,
                dom_planet_id=int(context["id"]),
            )
        assert resolved == colony_id
        assert audit["request_origin_planet"] == colony_id
        assert "Fleet Origin Scope Mismatch" in caplog.text
    finally:
        conn.close()


def test_api_game_state_includes_server_now(gc557c_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)

    from game.db import db

    conn = db()
    try:
        ok, err, user = create_user(f"gc557c_{uuid.uuid4().hex[:8]}", "test-pass-123")
        assert ok and user, err
        uid = int(user["id"])
        ensure_player_and_homeworld(uid, player_name="Cmd", conn=conn)
    finally:
        conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    resp = client.get("/api/game-state")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "server_now" in data
    assert int(data["server_now"]) == int(data["server_time"])


def test_static_gc557c_time_authority_contracts():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "function serverNow()" in src
    assert "function syncServerClockFromState(data)" in src
    assert "GC.serverNow = getTimerServerNow" in src
    assert "GC.debugTimers = function debugTimers()" in src
    assert "X-GC-Dom-Planet-Id" in src
    assert "function getTimerServerNow()" in src
    update = src.split("function updateAllProgressBars(serverNow)")[1][:400]
    assert "getTimerServerNow()" in update

    assert (ROOT / "game" / "fleet_origin.py").is_file()
    logic = (ROOT / "game" / "logic.py").read_text(encoding="utf-8")
    assert "def attach_canonical_server_time" in logic
    poll = (ROOT / "game" / "queue_poll.py").read_text(encoding="utf-8")
    assert "def player_fleet_is_dirty" in poll
