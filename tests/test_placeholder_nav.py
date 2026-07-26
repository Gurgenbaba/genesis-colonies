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
        "skilltree",
    }
    assert len(PLACEHOLDER_MODULES) == 2
    assert "premium" not in PLACEHOLDER_MODULES
    assert "galactic_politics" not in PLACEHOLDER_MODULES


def test_sidebar_has_military_and_trading_hub_nav():
    sidebar = _read("templates/partials/sidebar.html")
    sidebar_right = _read("templates/partials/sidebar_right.html")
    bottom = _read("templates/partials/bottom_utility_bar.html")
    assert 'data-nav-section="military"' in sidebar
    assert 'data-nav-module="shipyard"' in sidebar
    assert 'data-nav-module="defense"' in sidebar
    assert 'data-nav-module="fleet"' in sidebar
    assert 'data-nav-module="logistics"' not in sidebar
    assert "nav_logistics" not in sidebar
    assert 'data-nav-module="login_rewards"' in sidebar
    assert 'data-nav-module="premium"' in sidebar
    assert 'data-nav-section="economy"' in sidebar_right
    assert 'data-nav-module="trading"' in sidebar_right
    assert "url_for('trader_hub_view')" in sidebar_right
    assert "auction_house_view" in sidebar_right
    assert "url_for('alliance_view')" in sidebar_right
    assert "url_for('hall_of_fame_view')" in sidebar_right
    assert 'data-nav-module="hall_of_fame"' in sidebar_right
    assert "url_for('galactic_politics_view')" in sidebar_right
    assert 'data-nav-module="galactic_politics"' in sidebar_right
    assert 'data-nav-badge="government"' in sidebar_right
    # LiveOps + scoreboard moved out of the crowded right rail
    assert 'data-nav-module="login_rewards"' not in sidebar_right
    assert 'data-nav-module="ranking"' not in sidebar_right
    assert 'data-nav-module="records"' not in sidebar_right
    assert "url_for('ranking_view')" in bottom
    assert "url_for('chronicles_view')" in bottom
    assert "url_for('records_view')" in bottom
    assert "url_for('banned_players_view')" in bottom
    assert "gc-nav-wip-section" not in sidebar
    assert "gc-nav-wip-section" not in sidebar_right


def test_base_mobile_drawer_has_hall_of_fame_near_ranking():
    """HoF stays on the right community rail; Ranking lives in the bottom utility bar."""
    sidebar_right = _read("templates/partials/sidebar_right.html")
    bottom = _read("templates/partials/bottom_utility_bar.html")
    assert 'data-nav-module="hall_of_fame"' in sidebar_right
    assert "url_for('hall_of_fame_view')" in sidebar_right
    assert "url_for('ranking_view')" in bottom
    assert 'include "partials/sidebar_right.html"' in _read("templates/base.html")


def test_main_js_syncs_military_subnav():
    """Why old assert failed: subnav DOM ids are templated (`{{ _id_p }}nav-buildings-sub`), not literal in main.js.
    Still verifies JS accordion/sync owners and that the sidebar template wires the buildings subnav id."""
    src = _read("static/main.js")
    assert "tryHandleSubnavParentClick" in src
    assert "syncNavSectionAccordionState" in src
    assert "syncMilitarySubnav" in src
    assert "syncTradingSubnav" in src
    sidebar = _read("templates/partials/sidebar.html")
    assert "nav-buildings-sub" in sidebar


def test_placeholder_routes_render(placeholder_db):
    import importlib
    import app as app_mod

    from game.models import ensure_player_and_homeworld
    from game.db import db

    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uname = f"ph_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok and user, err
    conn = db()
    ensure_player_and_homeworld(int(user["id"]), player_name="PhTester", conn=conn)
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = int(user["id"])

    inv = client.get("/inventory")
    assert inv.status_code == 200
    assert "inventory-page" in inv.get_data(as_text=True)

    for slug in ("skilltree",):
        res = client.get(f"/{slug}")
        body = res.get_data(as_text=True)
        assert res.status_code == 200, slug
        assert "gc-placeholder-page" in body
        assert "gc-nav-wip-badge" in body or "gc-placeholder-badge" in body

    premium = client.get("/premium")
    assert premium.status_code == 200
    prem_body = premium.get_data(as_text=True)
    assert "battle-pass-page" in prem_body or "premium-page" in prem_body
    assert "gc-placeholder-page" not in prem_body

    login_rewards = client.get("/login-rewards")
    assert login_rewards.status_code == 200
    lr_body = login_rewards.get_data(as_text=True)
    assert "login-rewards-page" in lr_body

    banned = client.get("/banned-players")
    assert banned.status_code == 200
    assert "banned-players-page" in banned.get_data(as_text=True)

    politics = client.get("/galactic-politics")
    assert politics.status_code == 200
    assert "galactic-politics-page" in politics.get_data(as_text=True)

    auction = client.get("/auction-house")
    assert auction.status_code == 200
    assert "auction-house-page" in auction.get_data(as_text=True)
