"""
Placeholder nav modules and military submenu contracts.

Run: python -m pytest tests/test_placeholder_nav.py -v
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from game.models import create_user, init_db
from game.placeholder_pages import PLACEHOLDER_MODULES, list_placeholder_modules

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture()
def placeholder_db(tmp_path, monkeypatch):
    db_path = tmp_path / "placeholder_nav.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")

    from game import db as gdb

    gdb._DB_PATH = None
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_path


def test_placeholder_modules_registered():
    keys = {m["slug"] for m in list_placeholder_modules()}
    assert keys == {
        "auction-house",
        "galactic-politics",
        "skilltree",
        "premium",
    }
    assert len(PLACEHOLDER_MODULES) == 4


def test_sidebar_has_military_and_trading_hub_nav():
    sidebar = _read("templates/partials/sidebar.html")
    assert 'data-nav-section="military"' in sidebar
    assert 'data-nav-module="shipyard"' in sidebar
    assert 'data-nav-module="defense"' in sidebar
    assert 'data-nav-module="fleet"' in sidebar
    assert 'data-nav-module="logistics"' in sidebar
    assert 'data-nav-section="economy"' in sidebar
    assert 'data-nav-module="trading"' in sidebar
    assert "url_for('trader_hub_view')" in sidebar
    assert "auction_house_view" in sidebar
    assert "url_for('alliance_view')" in sidebar
    assert "url_for('hall_of_fame_view')" in sidebar
    assert 'data-nav-module="hall_of_fame"' in sidebar
    assert "url_for('records_view')" in sidebar
    assert 'data-nav-module="records"' in sidebar
    assert "gc-nav-wip-section" not in sidebar


def test_base_mobile_drawer_has_hall_of_fame_near_ranking():
    base = _read("templates/base.html")
    ranking_idx = base.find('data-nav-module="ranking"')
    hof_idx = base.find('data-nav-module="hall_of_fame"')
    assert ranking_idx >= 0
    assert hof_idx >= 0
    assert hof_idx > ranking_idx
    assert "url_for('hall_of_fame_view')" in base
    assert "gc-nav-drawer-link" in base.split("hall_of_fame", 1)[0]


def test_main_js_syncs_military_subnav():
    src = _read("static/main.js")
    assert "tryHandleSubnavParentClick" in src
    assert "syncNavSectionAccordionState" in src
    assert "syncMilitarySubnav" in src
    assert "syncTradingSubnav" in src
    assert "gc-nav-buildings-sub" in src


def test_placeholder_routes_render(placeholder_db):
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uname = f"ph_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err

    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])

    inv = client.get("/inventory")
    assert inv.status_code == 200
    assert "inventory-page" in inv.get_data(as_text=True)

    for slug in ("galactic-politics", "skilltree", "premium"):
        res = client.get(f"/{slug}")
        body = res.get_data(as_text=True)
        assert res.status_code == 200, slug
        assert "gc-placeholder-page" in body
        assert "gc-nav-wip-badge" in body or "gc-placeholder-badge" in body

    auction = client.get("/auction-house")
    assert auction.status_code == 200
    assert "auction-house-page" in auction.get_data(as_text=True)
