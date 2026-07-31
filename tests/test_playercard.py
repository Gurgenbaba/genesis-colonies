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
from game.db import commit, db, table_exists, begin_write_transaction
from game.models import create_user, init_db, upsert_player_score
from game.playercard import (
    AVATAR_OUTPUT_SIZE,
    AVATAR_UPLOAD_MAX_BYTES,
    SAVE_COOLDOWN_SEC,
    _LAST_SAVE_TS,
    avatar_api_path,
    avatar_public_path,
    avatar_storage_path,
    backfill_legacy_avatar_blobs,
    badge_image_default_path,
    badge_image_static_path,
    build_public_card,
    ensure_player_card,
    ensure_player_card_tables,
    get_player_avatar_row,
    get_player_card_row,
    player_avatar_exists,
    player_exists,
    local_avatar_file_usable,
    process_avatar_upload,
    resolve_avatar_display,
    save_own_card,
    sanitize_text_field,
    sort_badges_by_priority,
    upload_own_avatar,
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
        assert badge_count >= 11
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
    assert 'data-pc-field="avatar_file"' in edit_body

    save_avatar = client.post(
        "/api/player-card/me",
        data=json.dumps(
            {
                "title": "",
                "bio": "",
                "avatar_url": "https://example.com/zoom-avatar.png",
                "theme": "cyan",
                "is_public": "1",
            }
        ),
        content_type="application/json",
    )
    assert save_avatar.status_code == 200

    res_zoom = client.get(f"/api/player-card/{pid}")
    zoom_body = res_zoom.get_data(as_text=True)
    assert 'data-pc-avatar-zoom' in zoom_body
    assert 'data-pc-avatar-zoom-root' in zoom_body

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
    assert 'data-name-style="' in html
    assert "gc-player-name" in html
    assert "<img" not in html
    assert "&lt;img" in html or "onerror" not in html

    bad = app_mod.player_name_link(0, "Ghost")
    assert "data-player-card" not in str(bad)
    assert "Ghost" in str(bad) or "—" in str(bad)

    no_card = app_mod.player_name_link(5, "Nova", enable_card=False, name_style="plasma")
    no_html = str(no_card)
    assert 'data-name-style="plasma"' in no_html
    assert "data-player-card" not in no_html


def test_gc_player_name_html_mirrors_ssr_contract():
    """GC.playerNameHtml must emit the same attrs as player_name_link."""
    from pathlib import Path

    src = Path("static/main.js").read_text(encoding="utf-8")
    assert "GC.playerNameHtml = playerNameHtml" in src
    fn = src.split("function playerNameHtml(opts)")[1].split("GC.playerNameHtml = playerNameHtml")[0]
    assert "gc-player-name" in fn
    assert "data-name-style" in fn
    assert "data-player-id" in fn
    assert "data-player-card" in fn



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


def _png_bytes(width: int = 800, height: int = 600, color=(120, 80, 200, 255)) -> bytes:
    from io import BytesIO

    from PIL import Image

    im = Image.new("RGBA", (width, height), color)
    buf = BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _png_upload(width: int = 800, height: int = 600, color=(120, 80, 200, 255)):
    from io import BytesIO

    return (BytesIO(_png_bytes(width, height, color)), "avatar.png", "image/png")


class _FakeUpload:
    def __init__(self, data: bytes, mimetype: str = "image/png"):
        self._data = data
        self.mimetype = mimetype

    def read(self) -> bytes:
        return self._data


@pytest.fixture()
def avatar_storage(tmp_path, monkeypatch):
    root = tmp_path / "avatars"
    root.mkdir(parents=True)
    monkeypatch.setattr("game.playercard.avatar_storage_dir", lambda: root)
    monkeypatch.setattr(
        "game.playercard.avatar_storage_path",
        lambda pid: root / f"avatar_{int(pid)}.webp",
    )
    return root


def test_resolve_avatar_display_requires_db_blob(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_resolve")

    missing_url = avatar_api_path(pid)
    display, show = resolve_avatar_display(missing_url, 99, player_id=pid)
    assert display == ""
    assert show is False

    ok, path = process_avatar_upload(pid, _FakeUpload(_png_bytes()))
    assert ok is True
    assert path == avatar_api_path(pid)
    display2, show2 = resolve_avatar_display(path, 100, player_id=pid)
    assert show2 is True
    assert display2.startswith("/api/player-avatar/")
    assert player_avatar_exists(pid)


def test_save_own_card_preserves_avatar_when_form_empty(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_preserve")

    ok_up, _, _ = upload_own_avatar(pid, _FakeUpload(_png_bytes()))
    assert ok_up is True

    ok, reason, view = save_own_card(
        pid,
        {"title": "Bio only", "bio": "x", "avatar_url": "", "theme": "cyan", "is_public": "1"},
    )
    assert ok is True, reason
    row = get_player_card_row(pid)
    assert row["avatar_url"] == avatar_api_path(pid)
    assert view.get("avatar_url_client")


def test_validate_avatar_paths():
    ok, url = validate_avatar_url("/static/uploads/avatars/avatar_42.webp", player_id=42)
    assert ok is True
    assert url.endswith("avatar_42.webp")

    ok2, _ = validate_avatar_url("/static/uploads/avatars/avatar_42.webp", player_id=99)
    assert ok2 is False

    ok3, _ = validate_avatar_url("/static/uploads/avatars/evil.php", player_id=1)
    assert ok3 is False

    ok4, api_url = validate_avatar_url("/api/player-avatar/42", player_id=42)
    assert ok4 is True
    assert api_url == "/api/player-avatar/42"

    ok5, _ = validate_avatar_url("/api/player-avatar/42", player_id=99)
    assert ok5 is False


def test_process_avatar_upload_resizes_and_webp(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_proc")

    ok, path = process_avatar_upload(pid, _FakeUpload(_png_bytes(1200, 800)))
    assert ok is True
    assert path == avatar_api_path(pid)

    row = get_player_avatar_row(pid)
    assert row is not None
    blob = row["image_blob"]
    assert isinstance(blob, (bytes, memoryview))
    data = bytes(blob)
    assert len(data) < 100_000
    assert row["mime_type"] == "image/webp"

    from PIL import Image
    import io

    with Image.open(io.BytesIO(data)) as im:
        assert im.size == (AVATAR_OUTPUT_SIZE, AVATAR_OUTPUT_SIZE)
        assert im.format == "WEBP"


def test_process_avatar_rejects_invalid_types(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_reject")

    ok_gif, reason_gif = process_avatar_upload(
        pid,
        _FakeUpload(b"GIF89a" + b"\x00" * 32, mimetype="image/gif"),
    )
    assert ok_gif is False
    assert reason_gif == "playercard_avatar_invalid_type"

    ok_big, reason_big = process_avatar_upload(
        pid,
        _FakeUpload(b"\x00" * (AVATAR_UPLOAD_MAX_BYTES + 1)),
    )
    assert ok_big is False
    assert reason_big == "playercard_avatar_too_large"

    ok_svg, reason_svg = process_avatar_upload(
        pid,
        _FakeUpload(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", mimetype="image/png"),
    )
    assert ok_svg is False
    assert reason_svg == "playercard_avatar_invalid_type"


def test_avatar_upload_accepts_octet_stream_mime(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_octet")
    ok, path = process_avatar_upload(pid, _FakeUpload(_png_bytes(), mimetype="application/octet-stream"))
    assert ok is True, path
    assert player_avatar_exists(pid)


def test_backfill_legacy_avatar_blobs_imports_static_file(temp_db, avatar_storage, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_backfill")
    ensure_player_card(pid)
    legacy_path = avatar_storage / f"avatar_{pid}.webp"
    legacy_path.write_bytes(_png_bytes())

    conn = db()
    try:
        conn.execute(
            "UPDATE player_cards SET avatar_url = ? WHERE player_id = ?;",
            (avatar_public_path(pid), pid),
        )
        commit(conn)
    finally:
        conn.close()

    n = backfill_legacy_avatar_blobs()
    assert n >= 1
    assert player_avatar_exists(pid)
    row = get_player_card_row(pid)
    assert row["avatar_url"] == avatar_api_path(pid)


def test_upload_own_avatar_updates_db(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_db")

    ok, reason, view = upload_own_avatar(pid, _FakeUpload(_png_bytes()))
    assert ok is True
    assert reason == "playercard_avatar_upload_success"
    assert view is not None
    assert "/api/player-avatar/" in view.get("avatar_url_client", "")

    row = get_player_card_row(pid)
    assert row is not None
    assert row["avatar_url"] == avatar_api_path(pid)
    assert player_avatar_exists(pid)
    assert "?v=" in view["avatar_url"] or "&v=" in view["avatar_url"]


def test_api_avatar_upload_route(app_client):
    pid, login_name = _create_player("api_avatar")
    client = app_client
    client.post("/login", data={"username": login_name, "password": "test-pass-123"}, follow_redirects=True)

    res = client.post(
        "/api/player-card/me/avatar",
        data={"avatar": _png_upload()},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["card"]["show_avatar"] is True
    assert "/api/player-avatar/" in payload["card"]["avatar_url"]

    avatar_get = client.get(f"/api/player-avatar/{pid}")
    assert avatar_get.status_code == 200
    assert avatar_get.mimetype == "image/webp"
    assert len(avatar_get.data) >= 64

    edit = client.get(f"/api/player-card/{pid}/edit")
    assert edit.status_code == 200
    edit_body = edit.get_data(as_text=True)
    assert 'data-pc-field="avatar_file"' in edit_body
    assert "playercard_avatar_upload" in edit_body or "Avatar" in edit_body

    from io import BytesIO

    bad = client.post(
        "/api/player-card/me/avatar",
        data={"avatar": (BytesIO(b"not-an-image"), "bad.txt", "text/plain")},
    )
    assert bad.status_code == 400
    assert bad.get_json()["reason"] == "playercard_avatar_invalid_type"


def test_save_own_card_local_avatar_path(temp_db, monkeypatch):
    monkeypatch.setattr("game.playercard.SAVE_COOLDOWN_SEC", 0)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("avatar_save_path")

    ok_up, _, _ = upload_own_avatar(pid, _FakeUpload(_png_bytes()))
    assert ok_up is True

    ok, reason, view = save_own_card(
        pid,
        {
            "title": "Pilot",
            "bio": "",
            "avatar_url": avatar_api_path(pid),
            "theme": "cyan",
            "is_public": "1",
        },
    )
    assert ok is True
    assert reason == "playercard_save_success"
    assert view is not None
    assert "/api/player-avatar/" in view.get("avatar_url_client", "")


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
        assert n1 >= 11
    finally:
        conn.close()


def test_badge_image_static_paths():
    """GC-PERF-IMG: badge owner prefers WebP when the sibling exists on disk."""
    assert badge_image_static_path("founder") == "/static/img/badges/founder.webp"
    assert badge_image_static_path("builder_1k") == "/static/img/badges/builder.webp"
    assert badge_image_static_path("builder_10k") == "/static/img/badges/architect.webp"
    assert badge_image_static_path("researcher_1k") == "/static/img/badges/researcher.webp"
    assert badge_image_static_path("researcher_10k") == "/static/img/badges/scientist.webp"
    assert badge_image_static_path("commander_5k") == "/static/img/badges/commander.webp"
    assert badge_image_static_path("commander_50k") == "/static/img/badges/legend.webp"
    assert badge_image_static_path("bug_hunter") == "/static/img/badges/bughunter.webp"
    assert badge_image_static_path("community_hero") == "/static/img/badges/community.webp"
    assert badge_image_static_path("galactic_legend") == "/static/img/badges/galactic_legend.webp"
    assert badge_image_static_path("genesis") == "/static/img/badges/genesis.webp"
    assert badge_image_static_path("unknown_badge_key") == badge_image_default_path()
    assert badge_image_default_path().endswith((".webp", ".png"))


def test_badge_image_static_path_missing_asset_fallback(monkeypatch):
    monkeypatch.setattr(
        "game.playercard._project_root",
        lambda: Path("/nonexistent/project/root"),
    )
    assert badge_image_static_path("founder") == badge_image_default_path()


def test_sort_badges_by_priority():
    badges = [
        {"badge_key": "builder_1k", "rarity": "common", "requirement_value": 1000},
        {"badge_key": "genesis", "rarity": "mythic", "requirement_value": 0},
        {"badge_key": "commander_50k", "rarity": "epic", "requirement_value": 50000},
        {"badge_key": "founder", "rarity": "legendary", "requirement_value": 0},
    ]
    ordered = [b["badge_key"] for b in sort_badges_by_priority(badges)]
    assert ordered == ["genesis", "founder", "commander_50k", "builder_1k"]


def test_badge_seeds_use_empty_icon_not_unicode(temp_db):
    init_db()
    _close_db_conn()
    conn = db()
    try:
        rows = conn.execute(
            "SELECT badge_key, icon FROM player_card_badges ORDER BY badge_key;"
        ).fetchall()
        assert len(rows) >= 11
        for row in rows:
            icon = str(row["icon"] or "").strip()
            assert icon == "", f"badge {row['badge_key']} still has unicode icon: {icon!r}"
    finally:
        conn.close()


def test_new_badges_have_score_requirements(temp_db):
    init_db()
    _close_db_conn()
    conn = db()
    try:
        rows = {
            row["badge_key"]: row
            for row in conn.execute(
                """
                SELECT badge_key, requirement_type, requirement_value
                FROM player_card_badges
                WHERE badge_key IN ('genesis', 'galactic_legend', 'bug_hunter', 'community_hero');
                """
            ).fetchall()
        }
        assert rows["genesis"]["requirement_type"] == "score_planet_evolution"
        assert int(rows["genesis"]["requirement_value"]) == 10000
        assert rows["galactic_legend"]["requirement_type"] == "score_total"
        assert int(rows["galactic_legend"]["requirement_value"]) == 100000
        assert rows["bug_hunter"]["requirement_type"] == "score_defense"
        assert int(rows["bug_hunter"]["requirement_value"]) == 25000
        assert rows["community_hero"]["requirement_type"] == "score_fleet"
        assert int(rows["community_hero"]["requirement_value"]) == 15000
    finally:
        conn.close()


def test_sync_unlocks_score_based_badges(temp_db):
    _run_migrate(temp_db)
    init_db()
    _close_db_conn()
    pid, _ = _create_player("badge_unlock_user")
    conn = db()
    try:
        conn.execute(
            """
            UPDATE player_scores
            SET score_total = 100000,
                score_fleet = 15000,
                score_defense = 25000,
                score_planet_evolution = 10000
            WHERE player_id = ?;
            """,
            (int(pid),),
        )
        commit(conn)
    finally:
        conn.close()

    card, err = build_public_card(pid, viewer_id=pid, sync_badges=True)
    assert err is None
    unlocked_keys = {b["badge_key"] for b in (card.get("unlocked_badges") or [])}
    for key in ("founder", "genesis", "galactic_legend", "bug_hunter", "community_hero"):
        assert key in unlocked_keys, f"missing unlocked badge: {key}"


def test_unlocked_badges_include_image_url(temp_db):
    init_db()
    _close_db_conn()
    pid, _ = _create_player("badge_img_user")
    card, err = build_public_card(pid, viewer_id=pid, sync_badges=True)
    assert err is None
    unlocked = card.get("unlocked_badges") or []
    assert unlocked
    assert all(b.get("image_url", "").startswith("/static/img/badges/") for b in unlocked)


def test_playercard_view_includes_badge_zoom_markers(temp_db, app_client):
    init_db()
    _close_db_conn()
    pid, login_name = _create_player("badge_zoom_user")
    conn = db()
    try:
        build_public_card(pid, viewer_id=pid, sync_badges=True, conn=conn)
        founder = conn.execute(
            "SELECT id FROM player_card_badges WHERE badge_key = 'founder' LIMIT 1"
        ).fetchone()
        assert founder
        conn.execute(
            "UPDATE player_cards SET selected_badge_1 = ? WHERE player_id = ?",
            (int(founder["id"]), int(pid)),
        )
        commit(conn)
    finally:
        conn.close()

    client = app_client
    login = client.post(
        "/login",
        data={"username": login_name, "password": "test-pass-123"},
        follow_redirects=True,
    )
    assert login.status_code in (200, 302)

    res = client.get(f"/api/player-card/{pid}")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "data-pc-badge-zoom" in body
    assert "data-pc-media-zoom-root" in body
    assert "gc-badge-icon" in body
    # Prefer webp assets; png remains as onerror fallback.
    assert (
        "/static/img/badges/founder.webp" in body
        or "/static/img/badges/founder.png" in body
    )
    assert "onerror" in body
    assert "/static/img/badges/default.png" in body


def test_identity_shell_css_theme_rgb_not_overridden_by_shared_block():
    """Regression: shared :not(cyan) must not set --gc-id-rgb (higher specificity than
    [data-identity-theme=violet] would lock the shell to cyan)."""
    css = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    marker = ".gc-body-ingame[data-identity-theme]:not([data-identity-theme=\"cyan\"]) {"
    idx = css.find(marker)
    assert idx >= 0, "Identity Shell shared block missing"
    # First shared block after theme RGB list — grab until its closing brace at indent 0
    block_start = idx
    brace = css.find("{", block_start)
    depth = 0
    end = brace
    for i, ch in enumerate(css[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    shared = css[block_start : end + 1]
    assert "--gc-id-rgb:" not in shared, (
        "shared Identity Shell block must not declare --gc-id-rgb "
        "(specificity would override per-theme RGB)"
    )
    assert '[data-identity-theme="violet"] { --gc-id-rgb:' in css
    assert '[data-identity-theme="amber"] { --gc-id-rgb:' in css
    assert '[data-identity-theme="gold"] { --gc-id-rgb:' in css
    assert "data-identity-aura" in (
        Path(__file__).resolve().parents[1] / "templates" / "base.html"
    ).read_text(encoding="utf-8")
    assert '[data-identity-aura="aura_gold"] { --gc-aura-rgb:' in css
    assert '[data-identity-aura="aura_void"] { --gc-aura-rgb:' in css
    assert "gc-id-aura-pulse" in css


def test_get_equipped_identity_returns_theme_and_aura(temp_db):
    init_db()
    _close_db_conn()
    from game.playercard import get_equipped_identity

    pid, _ = _create_player("id_shell_user")
    ensure_player_card(pid)
    conn = db()
    try:
        conn.execute(
            "UPDATE player_cards SET theme = ?, aura_key = ? WHERE player_id = ?",
            ("violet", "aura_gold", int(pid)),
        )
        commit(conn)
    finally:
        conn.close()
    theme, aura = get_equipped_identity(pid)
    assert theme == "violet"
    assert aura == "aura_gold"


def test_public_card_shows_commander_class(temp_db):
    init_db()
    _run_migrate(temp_db)
    _close_db_conn()
    pid, _ = _create_player("card_class_owner")
    other, _ = _create_player("card_class_viewer")
    from game.commander_classes import pick_class, schema_ready

    conn = db()
    try:
        assert schema_ready(conn)
        begin_write_transaction(conn)
        ok, reason, _ = pick_class(pid, "vanguard", conn=conn)
        assert ok, reason
        commit(conn)
    finally:
        conn.close()
    card, err = build_public_card(pid, viewer_id=other)
    assert err is None
    assert card.get("is_private") is not True
    cc = card.get("commander_class")
    assert cc and cc.get("key") == "vanguard"
    assert cc.get("name_key")
    assert cc.get("portrait")
    ensure_player_card(pid)
    c = db()
    try:
        begin_write_transaction(c)
        cur = c.execute("UPDATE player_cards SET is_public = 0 WHERE player_id = ?", (pid,))
        assert int(cur.rowcount or 0) >= 1
        commit(c)
    finally:
        c.close()
    private_view, err2 = build_public_card(pid, viewer_id=other)
    assert err2 is None
    assert private_view.get("is_private") is True
    assert not private_view.get("commander_class")
