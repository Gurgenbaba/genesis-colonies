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


def test_public_card_shows_real_scores_and_rank(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_scores")
    other, _ = _create_player("card_scores_viewer")

    conn = db()
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = ?, score_buildings = ?, score_research = ?,
            score_fleet = 120, score_defense = 80
        WHERE player_id = ?
        """,
        (10000, 6000, 2500, pid),
    )
    conn.commit()
    conn.close()

    from game.ranking import build_ranking_api_payload, recalculate_ranks

    recalculate_ranks()

    card, err = build_public_card(pid, viewer_id=other)
    assert err is None and card is not None
    expected_total = 6000 + 2500 + 120 + 80
    assert card["score_total"] == expected_total
    assert card["score_buildings"] == 6000
    assert card["score_research"] == 2500
    assert card["score_fleet"] == 120
    assert card["score_defense"] == 80
    assert card.get("rank") is not None and int(card["rank"]) >= 1
    assert card.get("total_players") is not None and int(card["total_players"]) >= 1

    ranking = build_ranking_api_payload(pid, limit=100, refresh=False)
    assert int(card["rank"]) == int(ranking["current_player"]["rank"])
    assert int(card["score_total"]) == int(ranking["current_player"]["total_score"])


def test_playercard_rank_matches_ranking_with_stale_snapshot(temp_db):
    init_db()
    _close_db_conn()

    leader, _ = _create_player("rank_leader")
    runner, _ = _create_player("rank_runner")
    viewer, _ = _create_player("rank_viewer")

    conn = db()
    for pid, building, research in (
        (leader, 3000, 2000),
        (runner, 900, 600),
        (viewer, 50, 50),
    ):
        conn.execute(
            """
            UPDATE player_scores
            SET score_total = ?, score_buildings = ?, score_research = ?,
                score_fleet = 0, score_defense = 0
            WHERE player_id = ?
            """,
            (building + research, building, research, pid),
        )
    conn.execute(
        "UPDATE player_scores SET rank_total = 1 WHERE player_id = ?",
        (runner,),
    )
    conn.commit()
    conn.close()

    from game.ranking import build_ranking_api_payload

    ranking = build_ranking_api_payload(runner, limit=100, refresh=False)
    card, err = build_public_card(runner, viewer_id=viewer)
    assert err is None and card is not None

    assert int(card["rank"]) == 2
    assert int(ranking["current_player"]["rank"]) == 2
    assert int(card["rank"]) == int(ranking["current_player"]["rank"])

    card2, err2 = build_public_card(runner, viewer_id=viewer)
    assert err2 is None and card2 is not None
    assert int(card2["rank"]) == int(card["rank"])


def test_playercard_rank_stable_with_wrong_score_total_column(temp_db):
    init_db()
    _close_db_conn()

    high, _ = _create_player("rank_high")
    low, _ = _create_player("rank_low")

    conn = db()
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 100, score_buildings = 4000, score_research = 1000,
            score_fleet = 0, score_defense = 0
        WHERE player_id = ?
        """,
        (high,),
    )
    conn.execute(
        """
        UPDATE player_scores
        SET score_total = 9000, score_buildings = 200, score_research = 100,
            score_fleet = 0, score_defense = 0
        WHERE player_id = ?
        """,
        (low,),
    )
    conn.commit()
    conn.close()

    from game.ranking import build_ranking_api_payload, get_sorted_ranking_entries

    top = get_sorted_ranking_entries(limit=10)
    assert top[0]["player_id"] == high
    assert top[0]["total_score"] == 5000
    assert top[1]["player_id"] == low
    assert top[1]["total_score"] == 300

    card, err = build_public_card(high, viewer_id=low)
    assert err is None and card is not None
    assert card["score_total"] == 5000
    assert int(card["rank"]) == 1

    ranking = build_ranking_api_payload(high, limit=10, refresh=False)
    assert int(card["rank"]) == int(ranking["current_player"]["rank"])


def test_public_card_without_score_row_shows_zero_with_rank(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_zero")
    other, _ = _create_player("card_zero_viewer")
    conn = db()
    conn.execute("DELETE FROM player_scores WHERE player_id = ?", (pid,))
    conn.commit()
    conn.close()

    card, err = build_public_card(pid, viewer_id=other)
    assert err is None and card is not None
    assert card["score_total"] == 0
    assert card["score_buildings"] == 0
    assert card["score_research"] == 0
    assert card.get("rank") is not None and int(card["rank"]) >= 1


def test_public_card_and_private_profile(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("card_alpha")
    other, _ = _create_player("card_beta")

    card, err = build_public_card(pid, viewer_id=other, sync_badges=True)
    assert err is None
    assert card is not None
    assert "card_alpha" in card["commander_name"]
    assert card["score_total"] >= 4000
    assert card["score_buildings"] >= 2500
    assert card["score_research"] >= 1500
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
    assert "card" in payload
    assert payload["card"]["player_id"] == pid
    assert "avatar_version" in payload["card"]
    assert "Star Marshal" in payload["html"]
    assert "playercard_loading" not in payload["html"].lower() or "Lade Profil" not in payload["html"]

    save_avatar = client.post(
        "/api/player-card/me",
        data=json.dumps(
            {
                "title": "Star Marshal",
                "bio": "Explorer of the rim.",
                "avatar_url": "https://example.com/pc-avatar.png",
                "theme": "cyan",
                "is_public": "1",
            }
        ),
        content_type="application/json",
    )
    assert save_avatar.status_code == 200
    av_payload = save_avatar.get_json()
    assert av_payload["ok"] is True
    assert av_payload["card"]["show_avatar"] is True
    assert "example.com/pc-avatar.png" in av_payload["card"]["avatar_url"]
    assert "?v=" in av_payload["card"]["avatar_url"] or "&v=" in av_payload["card"]["avatar_url"]


def test_modal_shell_has_separate_content_and_loading(app_client):
    pid, login_name = _create_player("api_shell")
    client = app_client
    client.post("/login", data={"username": login_name, "password": "test-pass-123"}, follow_redirects=True)

    page = client.get("/ranking").get_data(as_text=True)
    assert 'data-pc-content' in page
    assert 'data-pc-loading' in page
    assert 'data-pc-error' in page


def test_player_name_link_escapes_and_valid_id(app_client):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    link = app_mod.player_name_link(5, '<img onerror="x">')
    html = str(link)
    assert 'data-player-id="5"' in html
    assert "<img" not in html
    assert "&lt;img" in html or "onerror" not in html

    bad = app_mod.player_name_link(0, "Ghost")
    assert "data-player-card" not in str(bad)
    assert "Ghost" in str(bad) or "—" in str(bad)


def test_session_user_id_matches_player_id(temp_db):
    init_db()
    _close_db_conn()
    pid, uname = _create_player("id_match")
    conn = db()
    try:
        row = conn.execute(
            "SELECT u.id AS user_id, p.id AS player_id FROM users u JOIN players p ON p.id = u.id WHERE u.username LIKE ?",
            (f"{uname}%",),
        ).fetchone()
        assert row is not None
        assert int(row["user_id"]) == int(row["player_id"]) == pid
    finally:
        conn.close()


def test_private_card_minimal_fields(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("priv_a")
    other, _ = _create_player("priv_b")
    ensure_player_card(other)
    c = db()
    try:
        c.execute("UPDATE player_cards SET is_public = 0 WHERE player_id = ?", (other,))
        commit(c)
    finally:
        c.close()

    view, err = build_public_card(other, viewer_id=pid)
    assert err is None
    assert view.get("is_private") is True
    assert "avatar_url" not in view or not view.get("avatar_url")
    assert view.get("score_total") is None or "score_total" not in view


def test_header_commander_link_uses_player_id(app_client):
    pid, login_name = _create_player("header_link")
    client = app_client
    client.post("/login", data={"username": login_name, "password": "test-pass-123"}, follow_redirects=True)

    page = client.get("/overview").get_data(as_text=True)
    assert f'data-player-id="{pid}"' in page
    assert 'data-player-card="1"' in page
    assert "gc-user-name" in page


def test_fallback_player_page(app_client):
    pid, login_name = _create_player("fallback_user")
    client = app_client
    client.post("/login", data={"username": login_name, "password": "test-pass-123"}, follow_redirects=True)

    res = client.get(f"/player/{pid}")
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert "player-card-page" in body
    assert "gc-player-card-view" in body
    assert "playercard_back_to_game" in body or "Zurück zur Übersicht" in body
    assert "playercard_fallback_edit_hint" in body or "AJAX" in body
    # Modal shell may include loading copy; SSR card must not be stuck on loading only.
    assert "gc-player-card-stat" in body or "gc-player-card-private" in body


def test_fallback_private_player(app_client):
    owner, owner_name = _create_player("fallback_priv")
    viewer, viewer_login = _create_player("fallback_view")
    ensure_player_card(owner)
    c = db()
    try:
        c.execute("UPDATE player_cards SET is_public = 0 WHERE player_id = ?", (owner,))
        commit(c)
    finally:
        c.close()

    client = app_client
    client.post("/login", data={"username": viewer_login, "password": "test-pass-123"}, follow_redirects=True)
    res = client.get(f"/player/{owner}")
    assert res.status_code == 200
    assert "playercard_private_profile" in res.get_data(as_text=True) or "privat" in res.get_data(as_text=True).lower()


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
