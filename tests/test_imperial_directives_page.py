"""GC-914A/B — Imperial Directives page and live-state tests."""

from __future__ import annotations

import importlib
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
from game.directives.generator import STATUS_COMPLETED, ensure_player_directives
from game.directives.service import get_imperial_directives_state
from game.live_state import imperial_directives_for_game_state, nav_badges_for_game_state
from game.models import create_user

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def id_page_db(tmp_path, monkeypatch):
    db_file = tmp_path / "imperial_directives_page.db"
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
    yield db_file


@pytest.fixture()
def page_client(id_page_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True

    uname = f"id_page_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    player_id = int(user["id"])

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = player_id
    return client, player_id


def _mark_claimable(conn, player_id: int) -> None:
    ts = time.time()
    ensure_player_directives(player_id, conn=conn, now=ts)
    conn.execute(
        """
        UPDATE player_directives
        SET progress_value = target_value, status = ?
        WHERE player_id = ? AND id = (
            SELECT id FROM player_directives WHERE player_id = ? ORDER BY id ASC LIMIT 1
        );
        """,
        (STATUS_COMPLETED, player_id, player_id),
    )
    conn.commit()


def test_imperial_directives_page_renders(page_client):
    client, _pid = page_client
    r = client.get("/imperial-directives")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="imperial-directives-page"' in html
    assert "data-imperial-directives" in html
    assert "id-directives-main-frame" in html
    assert 'data-id-directive-list="orders"' in html
    assert "inventory-loot-card" in html or "data-id-directive-list" in html
    assert html.count("data-directive-card") == 4
    assert "inventory-loot-card-name" in html
    assert 'data-id-directive-list="daily"' not in html
    assert 'data-id-directive-list="weekly"' not in html
    assert 'data-special-window="imperial-directives"' not in html


def test_imperial_directives_persist_after_page_load(id_page_db):
    """Generated directives must survive conn.close() (commit after ensure)."""
    conn = db()
    try:
        ok, _, user = create_user(f"id_persist_{uuid.uuid4().hex[:8]}", "secret123")
        assert ok and user
        player_id = int(user["id"])

        get_imperial_directives_state(player_id, conn=conn)
        conn.commit()
    finally:
        conn.close()

    conn2 = db()
    try:
        count = conn2.execute(
            "SELECT COUNT(*) FROM player_directives WHERE player_id = ?;",
            (player_id,),
        ).fetchone()[0]
        assert int(count) == 4
    finally:
        conn2.close()


def test_api_imperial_directives_state_returns_full_cards(page_client):
    client, _pid = page_client
    r = client.get("/api/imperial-directives/state")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    payload = body["imperial_directives"]
    assert payload["ready"] is True
    assert len(payload["directives"]) == 4
    first = payload["directives"][0]
    assert first.get("title_key")
    assert first.get("description_key")
    assert "rewards_preview" in first
    assert "progress" in first


def test_api_game_state_includes_imperial_directives_summary_only(page_client):
    client, _pid = page_client
    # Bare /api/game-state is the lightweight poll path and diets
    # "imperial_directives" out of the payload; include_panel=1 requests the
    # full panel refresh (GC-STABILIZE-002; app.py api_game_state).
    r = client.get("/api/game-state?include_panel=1")
    assert r.status_code == 200
    state = r.get_json()
    assert state["ok"] is True
    assert "imperial_directives" in state
    summary = state["imperial_directives"]
    assert summary["ready"] is True
    assert "directives" not in summary
    assert summary["daily_total"] == 3
    assert summary["weekly_total"] == 1
    assert "claimable_count" in summary
    assert "daily_reset_at" in summary
    assert "nav_badges" in state
    assert "imperial_directives" in state["nav_badges"]


def test_nav_badge_active_when_directive_claimable(id_page_db):
    conn = db()
    try:
        ok, _, user = create_user(f"id_badge_{uuid.uuid4().hex[:8]}", "secret123")
        assert ok and user
        player_id = int(user["id"])
        _mark_claimable(conn, player_id)
        badges = nav_badges_for_game_state(player_id, conn=conn)
        assert badges["imperial_directives"]["active"] is True
        assert badges["imperial_directives"]["count"] >= 1
    finally:
        conn.close()


def test_live_state_slice_is_summary_not_full_cards(id_page_db):
    conn = db()
    try:
        ok, _, user = create_user(f"id_slice_{uuid.uuid4().hex[:8]}", "secret123")
        assert ok and user
        player_id = int(user["id"])
        summary = imperial_directives_for_game_state(player_id, conn=conn)
        assert summary["ready"] is True
        assert summary["claimable_count"] == 0
        assert summary["daily_total"] == 3
        assert summary["weekly_total"] == 1
        assert "directives" not in summary
    finally:
        conn.close()
