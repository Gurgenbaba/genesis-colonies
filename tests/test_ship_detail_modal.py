"""Ship detail modal and fuel cells HUD (no storage cap)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import game.db as gdb
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.ship_detail import build_ship_detail_card


@pytest.fixture
def ship_detail_db(tmp_path, monkeypatch):
    db_path = tmp_path / "ship_detail.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    ok, err, user = create_user(f"sd_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def test_base_template_fuel_cells_with_storage_cap():
    root = Path(__file__).resolve().parent.parent
    html = (root / "templates" / "base.html").read_text(encoding="utf-8")
    assert "hud-res-fuel-cells" in html
    assert "res-value fuel_cells" in html
    assert "res-cap fuel_cells" in html
    assert "hud-res-no-storage" not in html


def test_base_includes_ship_detail_modal_shell():
    root = Path(__file__).resolve().parent.parent
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    modal = (root / "templates" / "partials" / "ship_detail_modal.html").read_text(encoding="utf-8")
    assert "partials/ship_detail_modal.html" in base
    assert "gc-ship-detail-root" in modal


def test_build_ship_detail_card_known_ship():
    card, err = build_ship_detail_card("mule_courier")
    assert err is None
    assert card is not None
    assert card["ship_key"] == "mule_courier"
    assert card["cargo"] == 5000
    assert card["build_cost_metal"] > 0


def test_build_ship_detail_card_legacy_key():
    card, err = build_ship_detail_card("small_cargo")
    assert err is None
    assert card is not None
    assert card["ship_key"] == "mule_courier"


def test_build_ship_detail_card_unknown():
    card, err = build_ship_detail_card("unknown_hull_xyz")
    assert card is None
    assert err == "ship_detail_not_found"


def test_api_ship_detail_returns_html(ship_detail_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get(
        "/api/ships/mule_courier",
        headers={"X-Requested-With": "XMLHttpRequest", "Accept": "text/html"},
    )
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "gc-ship-detail-shell" in body
    assert "gc-player-card-stat" in body


def test_api_ship_detail_not_found(ship_detail_db, monkeypatch):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    uid = _player()
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    r = client.get("/api/ships/not_a_real_ship")
    assert r.status_code == 404


def test_shipyard_and_fleet_have_detail_triggers():
    root = Path(__file__).resolve().parent.parent
    shipyard = (root / "templates" / "shipyard.html").read_text(encoding="utf-8")
    fleet = (root / "templates" / "fleet.html").read_text(encoding="utf-8")
    js = (root / "static" / "main.js").read_text(encoding="utf-8")
    assert 'data-ship-detail="' in shipyard
    assert "gc-ship-detail-trigger" in shipyard
    assert "render_info_popover_trigger" in shipyard
    assert "gc-ship-card-desc" not in shipyard
    assert 'class="gc-prog-info gc-popover-trigger" title=' not in shipyard
    assert 'data-ship-detail="{{ ship.key }}"' in fleet
    assert "initShipDetailOnce" in js
    assert "GC.openShipDetail" in js
