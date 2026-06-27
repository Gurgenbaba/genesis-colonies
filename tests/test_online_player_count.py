"""Online player count — canonical last_seen window (HUD + landing)."""

from __future__ import annotations

import os
import re
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
    ONLINE_WINDOW_SEC,
    create_user,
    ensure_player_and_homeworld,
    get_online_player_count,
    get_player_stats,
    init_db,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def online_db(tmp_path, monkeypatch):
    db_file = tmp_path / "online_player_count.db"
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
    yield db_file
    try:
        db().close()
    except Exception:
        pass


@pytest.fixture()
def app_client(online_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def _create_player(name_prefix: str = "cmd") -> int:
    ok, err, user = create_user(f"{name_prefix}_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _set_last_seen(player_id: int, last_seen: int) -> None:
    conn = db()
    try:
        conn.execute(
            "UPDATE players SET last_seen = ? WHERE id = ?;",
            (int(last_seen), int(player_id)),
        )
        conn.commit()
    finally:
        conn.close()


def test_online_player_within_window_counts(online_db):
    now = int(time.time())
    pid = _create_player("online")
    _set_last_seen(pid, now - 60)

    assert get_online_player_count(now=now) == 1


def test_online_player_outside_window_not_counted(online_db):
    now = int(time.time())
    pid = _create_player("offline")
    _set_last_seen(pid, now - ONLINE_WINDOW_SEC - 1)

    assert get_online_player_count(now=now) == 0


def test_get_player_stats_online_matches_helper(online_db):
    now = int(time.time())
    online_pid = _create_player("recent")
    stale_pid = _create_player("stale")
    _set_last_seen(online_pid, now - 30)
    _set_last_seen(stale_pid, now - ONLINE_WINDOW_SEC - 120)

    stats = get_player_stats()
    assert stats["online_now"] == get_online_player_count(now=now)
    assert stats["online_now"] == 1


def test_landing_renders_server_online_count(app_client, online_db):
    now = int(time.time())
    online_pid = _create_player("landing_online")
    stale_pid = _create_player("landing_stale")
    _set_last_seen(online_pid, now)
    _set_last_seen(stale_pid, now - ONLINE_WINDOW_SEC - 60)

    resp = app_client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    match = re.search(
        r'landing-stat-tile-online[\s\S]*?landing-stat-online[\s\S]*?(\d+)',
        html,
    )
    assert match, "landing online tile missing from HTML"
    assert int(match.group(1)) == 1
