"""Ship icons, shipyard polling contracts, ship detail API, build UX guards."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import game.db as gdb
from game.db import db
from game.fleet_defs import SHIPS, all_ship_keys, ship_icon_filename
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.ship_detail import build_ship_detail_card

ROOT = Path(__file__).resolve().parent.parent
SHIPS_IMG = ROOT / "static" / "img" / "ships"


@pytest.fixture
def ship_assets_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ship_assets.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    ok, err, user = create_user(f"sa_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def test_all_known_ship_icons_exist_on_disk():
    missing = []
    for key in sorted(all_ship_keys()):
        fname = ship_icon_filename(key)
        path = SHIPS_IMG / fname
        if not path.is_file():
            missing.append(fname)
    assert not missing, f"Missing ship PNGs: {missing}"


def test_eclipse_runner_icon_file_exists():
    assert (SHIPS_IMG / "eclipse_runner.png").is_file()


def test_ship_detail_view_avoids_requirements_items_dot_access():
    tpl = (ROOT / "templates" / "partials" / "ship_detail_view.html").read_text(encoding="utf-8")
    assert "requirements.items" not in tpl
    assert "requirements_items" in tpl


def test_shipyard_template_avoids_requirements_items_dot_access():
    tpl = (ROOT / "templates" / "shipyard.html").read_text(encoding="utf-8")
    assert "requirements.items" not in tpl


def test_build_ship_detail_card_exposes_requirements_items(ship_assets_db):
    uid = _player()
    conn = db()
    try:
        from game.models import get_planet_buildings, get_research_levels
        from game.planet_evolution.repository import get_context_planet

        planet = get_context_planet(uid, conn=conn)
        buildings = get_planet_buildings(int(planet["id"]), conn=conn)
        research = get_research_levels(user_id=uid, conn=conn)
    finally:
        conn.close()

    card, err = build_ship_detail_card("atlas_hauler", buildings=buildings, research=research)
    assert err is None
    assert card is not None
    assert isinstance(card.get("requirements_items"), list)
    assert len(card["requirements_items"]) > 0

    card2, _ = build_ship_detail_card("spark_drone")
    assert card2 is not None
    assert card2.get("requirements_items", []) == []


def test_api_ship_detail_atlas_and_mule_return_200(ship_assets_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    for key in ("mule_courier", "atlas_hauler"):
        r = client.get(
            f"/api/ships/{key}",
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"},
        )
        assert r.status_code == 200, key
        body = r.get_data(as_text=True)
        assert "gc-ship-detail-shell" in body
        assert "requirements.items" not in body


def test_main_js_shipyard_polling_idempotent_and_cleanup():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "stopShipyardTimers" in src
    assert "startShipyardTimers" in src
    assert "GC.registerCleanup(stopShipyardTimers)" in src
    assert "function updatePageTimers(serverNow)" in src
    assert "_pageTimerLoopRunning" in src
    shipyard_tpl = (ROOT / "templates" / "shipyard.html").read_text(encoding="utf-8")
    queue_macros = (ROOT / "templates" / "partials" / "card_queue_macros.html").read_text(encoding="utf-8")
    assert "render_card_queue_timer" in shipyard_tpl
    assert "data-timer-target" in queue_macros
    assert "queuePollBound" not in src


def test_main_js_shipyard_build_button_loading_guard():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    idx = src.index('const buildBtn = e.target.closest("[data-shipyard-build]")')
    block = src[idx : idx + 2200]
    assert "buildBtn.dataset.building" in block
    assert "is-loading" in block
    assert "dataset.canBuild" in block
    assert "reasonText(errKey)" in block
