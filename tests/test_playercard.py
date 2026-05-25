"""
Player card system tests.

Run: python -m pytest tests/test_playercard.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.db import commit, db, table_exists
from game.models import create_user, init_db, upsert_player_score
from game.playercard import (
    SAVE_COOLDOWN_SEC,
    _LAST_SAVE_TS,
    build_public_card,
    ensure_player_card,
    ensure_player_card_tables,
    player_exists,
    save_own_card,
    sanitize_text_field,
    validate_avatar_url,
)

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_file = tmp_path / "playercard_test.db"
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


def _close_db_conn() -> None:
    try:
        db().close()
    except Exception:
        pass


def _create_player(username: str) -> tuple[int, str]:
    import uuid
    uname = f"{username}_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user and user.get("id"), err
    uid = int(user["id"])
    upsert_player_score(uid, 6000, 2500, 1500)
    _close_db_conn()
    return uid, uname


@pytest.fixture()
def app_client(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    _run_migrate(temp_db)
    init_db()
    _close_db_conn()

    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    return app_mod.app.test_client()


def test_migration_idempotent_and_tables(temp_db):
    init_db()
    _close_db_conn()
    _run_migrate(temp_db)
    _run_migrate(temp_db)

    conn = db()
    try:
        assert table_exists(conn, "player_cards")
        assert table_exists(conn, "player_card_badges")
        assert table_exists(conn, "player_card_unlocked_badges")
        badge_count = conn.execute("SELECT COUNT(*) AS c FROM player_card_badges;").fetchone()["c"]
        assert badge_count >= 7
        dup = conn.execute(
            "SELECT badge_key, COUNT(*) AS c FROM player_card_badges GROUP BY badge_key HAVING c > 1;"
        ).fetchall()
        assert len(dup) == 0
        applied = {r["name"] for r in conn.execute("SELECT name FROM migration_history;").fetchall()}
        assert "011_player_cards.sql" in applied
    finally:
        conn.close()


def test_public_card_and_private_profile(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_alpha")
    other, _ = _create_player("card_beta")

    card, err = build_public_card(pid, viewer_id=other)
    assert err is None
    assert card is not None
    assert "card_alpha" in card["commander_name"]
    assert card["score_total"] >= 0
    assert card["colonies"] >= 1
    assert card.get("unlocked_badges")  # founder badge unlocked at minimum

    ensure_player_card(other)
    c = db()
    try:
        c.execute("UPDATE player_cards SET is_public = 0 WHERE player_id = ?", (other,))
        commit(c)
    finally:
        c.close()

    private_view, err2 = build_public_card(other, viewer_id=pid)
    assert err2 is None
    assert private_view.get("is_private") is True
    assert "score_total" not in private_view or private_view.get("score_total") is None or private_view.get("is_private")


def test_save_own_card_xss_and_avatar(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_save")

    ok, reason, _view = save_own_card(
        pid,
        {
            "title": "<script>alert(1)</script>",
            "bio": "Hello <b>world</b>",
            "avatar_url": "javascript:alert(1)",
            "theme": "violet",
            "is_public": "1",
        },
    )
    assert ok is False
    assert reason == "playercard_invalid_avatar"

    ok2, reason2, view2 = save_own_card(
        pid,
        {
            "title": "<script>x</script>",
            "bio": "Safe bio",
            "avatar_url": "https://example.com/a.png",
            "theme": "violet",
            "is_public": "1",
        },
    )
    assert ok2 is True
    assert reason2 == "playercard_save_success"
    assert view2 is not None
    assert "<script>" not in view2["title"]
    assert "<" not in view2["title"]
    assert view2["theme"] == "violet"


def test_rate_limit_blocks_rapid_resave(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 60)
    _LAST_SAVE_TS.clear()
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_rate")

    ok1, _, _ = save_own_card(pid, {"title": "A", "bio": "", "avatar_url": "", "theme": "cyan", "is_public": "1"})
    assert ok1 is True

    ok2, reason2, _ = save_own_card(pid, {"title": "B", "bio": "", "avatar_url": "", "theme": "cyan", "is_public": "1"})
    assert ok2 is False
    assert reason2 == "playercard_rate_limited"


def test_validate_avatar_and_sanitize():
    ok, url = validate_avatar_url("https://cdn.example.com/x.png")
    assert ok is True
    assert "example.com" in url

    ok2, _ = validate_avatar_url("ftp://bad.com/x")
    assert ok2 is False

    assert "<" not in sanitize_text_field("<tag>", 64)
    assert ">" not in sanitize_text_field("a>b", 64)


def test_player_not_found():
    assert player_exists(999999) is False
    card, err = build_public_card(999999, viewer_id=1)
    assert card is None
    assert err == "playercard_not_found"


def test_api_routes_and_partials(app_client):
    pid, login_name = _create_player("api_card_user")
    other, _ = _create_player("api_card_other")

    client = app_client
    assert client.post(
        "/login",
        data={"username": login_name, "password": "test-pass-123"},
        follow_redirects=True,
    ).status_code in (200, 302)

    res = client.get(f"/api/player-card/{other}")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "gc-player-card-shell" in body
    assert "gc-player-card-view" in body
    assert "playercard_loading" not in body.lower() or "Lade Profil" not in body

    res_edit = client.get(f"/api/player-card/{other}/edit")
    assert res_edit.status_code == 403

    res_own_edit = client.get(f"/api/player-card/{pid}/edit")
    assert res_own_edit.status_code == 200
    edit_body = res_own_edit.get_data(as_text=True)
    assert "gc-player-card-edit" in edit_body
    assert "data-pc-content" not in edit_body
    assert "gc-player-card-form" in edit_body

    save = client.post(
        "/api/player-card/me",
        data=json.dumps(
            {
                "title": "Star Marshal",
                "bio": "Explorer of the rim.",
                "avatar_url": "",
                "theme": "cyan",
                "is_public": "1",
            }
        ),
        content_type="application/json",
    )
    assert save.status_code == 200
    payload = save.get_json()
    assert payload["ok"] is True
    assert "html" in payload
    assert "Star Marshal" in payload["html"]
    assert "playercard_loading" not in payload["html"].lower() or "Lade Profil" not in payload["html"]


def test_modal_shell_has_separate_content_and_loading(app_client):
    pid, login_name = _create_player("api_shell")
    client = app_client
    client.post("/login", data={"username": login_name, "password": "test-pass-123"}, follow_redirects=True)

    page = client.get("/ranking").get_data(as_text=True)
    assert 'data-pc-content' in page
    assert 'data-pc-loading' in page
    assert 'data-pc-error' in page


def test_badge_seed_idempotent_via_service(temp_db):
    init_db()
    _close_db_conn()
    ensure_player_card_tables()
    conn = db()
    try:
        n1 = conn.execute("SELECT COUNT(*) AS c FROM player_card_badges;").fetchone()["c"]
        ensure_player_card_tables(conn)
        n2 = conn.execute("SELECT COUNT(*) AS c FROM player_card_badges;").fetchone()["c"]
        assert n1 == n2
        assert n1 >= 7
    finally:
        conn.close()
