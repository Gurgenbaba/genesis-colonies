"""Buildings UI preference — Colony Stage vs Retro cards."""

from __future__ import annotations

import importlib
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.models import create_user, init_db
from game.options import (
    DEFAULT_BUILDINGS_UI_MODE,
    get_buildings_ui_settings,
    normalize_buildings_ui_mode,
    update_buildings_ui_settings,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def bui_db(tmp_path, monkeypatch):
    db_path = tmp_path / "buildings_ui.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    init_db()
    yield
    dbmod._DB_PATH = None


def _create_player():
    uname = f"bui_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "pw1234")
    assert ok and user, err
    return int(user["id"]), uname


def _app_client(monkeypatch):
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _login(client, player_id: int, username: str):
    with client.session_transaction() as sess:
        sess["user_id"] = int(player_id)
        sess["username"] = username


def test_normalize_buildings_ui_mode_default():
    assert normalize_buildings_ui_mode(None) == DEFAULT_BUILDINGS_UI_MODE
    assert normalize_buildings_ui_mode("nope") == "stage"
    assert normalize_buildings_ui_mode("STAGE") == "stage"
    assert normalize_buildings_ui_mode("cards") == "cards"


def test_buildings_ui_defaults_prompt_pending(bui_db):
    pid, _ = _create_player()
    settings = get_buildings_ui_settings(pid)
    assert settings["buildings_ui_mode"] == "stage"
    assert settings["buildings_ui_prompt_pending"] is True


def test_update_buildings_ui_marks_choice_done(bui_db):
    pid, _ = _create_player()
    ok, err, data = update_buildings_ui_settings(
        pid, buildings_ui_mode="cards", mark_choice_done=True
    )
    assert ok is True
    assert err == "options_saved"
    assert data["buildings_ui_mode"] == "cards"
    assert data["buildings_ui_prompt_pending"] is False

    again = get_buildings_ui_settings(pid)
    assert again["buildings_ui_mode"] == "cards"
    assert again["buildings_ui_prompt_pending"] is False


def test_options_update_does_not_rearm_prompt(bui_db):
    pid, _ = _create_player()
    update_buildings_ui_settings(pid, buildings_ui_mode="stage", mark_choice_done=True)
    ok, _, data = update_buildings_ui_settings(
        pid, buildings_ui_mode="cards", mark_choice_done=False
    )
    assert ok is True
    assert data["buildings_ui_mode"] == "cards"
    assert data["buildings_ui_prompt_pending"] is False


def test_update_rejects_invalid_mode(bui_db):
    pid, _ = _create_player()
    ok, err, _ = update_buildings_ui_settings(pid, buildings_ui_mode="neon")
    assert ok is False
    assert err == "options_error_invalid_buildings_ui"


def test_api_buildings_ui_and_ssr_modes(bui_db, monkeypatch):
    pid, uname = _create_player()
    client = _app_client(monkeypatch)
    _login(client, pid, uname)

    bad = client.post(
        "/api/options/buildings-ui",
        json={"buildings_ui_mode": "invalid"},
        headers={"Accept": "application/json"},
    )
    assert bad.status_code == 400

    res = client.post(
        "/api/options/buildings-ui",
        json={"buildings_ui_mode": "cards", "mark_choice_done": True},
        headers={"Accept": "application/json"},
    )
    body = res.get_json()
    assert res.status_code == 200
    assert body["ok"] is True
    assert body["data"]["buildings_ui_mode"] == "cards"
    assert body["data"]["buildings_ui_prompt_pending"] is False

    cards_html = client.get("/buildings").get_data(as_text=True)
    assert 'data-buildings-ui-mode="cards"' in cards_html
    assert "data-bld-planet-stage" not in cards_html
    assert "data-bld-cards-panel" in cards_html
    assert 'data-bld-cards-mode="retro"' in cards_html

    client.post(
        "/api/options/buildings-ui",
        json={"buildings_ui_mode": "stage"},
        headers={"Accept": "application/json"},
    )
    stage_html = client.get("/buildings").get_data(as_text=True)
    assert 'data-buildings-ui-mode="stage"' in stage_html
    assert "data-bld-planet-stage" in stage_html
    assert "data-bld-cards-panel" not in stage_html


def test_options_snapshot_includes_buildings_ui(bui_db):
    from game.options import get_options_snapshot

    pid, _ = _create_player()
    snap = get_options_snapshot(pid)
    assert snap.get("buildings_ui_mode") == "stage"
    assert snap.get("buildings_ui_prompt_pending") is True


def test_chooser_partial_in_base():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "buildings_ui_chooser.html" in base
    chooser = (ROOT / "templates" / "partials" / "buildings_ui_chooser.html").read_text(
        encoding="utf-8"
    )
    assert "gc-bld-ui-chooser" in chooser
    assert 'data-bld-ui-choice="stage"' in chooser
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "initBuildingsUiChooser" in main
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gc-bld-ui-chooser{" in css
    chunk = css.split(".gc-bld-ui-chooser{")[1].split("}")[0]
    assert "position: fixed" in chunk
    assert "place-items: center" in chunk
