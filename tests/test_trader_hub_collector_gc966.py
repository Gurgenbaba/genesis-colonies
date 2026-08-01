"""GC-966 — Trader Hub Collector Exchange UI integration tests."""

from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import app as app_module
import game.db as dbmod
import game.models as models
from game.collector_catalog import COLLECTOR_OFFERS
from game.collector_exchange import build_collector_exchange_payload, sort_offers_for_display
from game.db import db
from game.inventory import grant_inventory_item, inventory_schema_ready
from game.models import create_user, ensure_player_and_homeworld, init_db

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
MAIN_JS = ROOT / "static" / "main.js"
LOCALES = ROOT / "locales"


@pytest.fixture
def trader_collector_db(tmp_path, monkeypatch):
    db_path = tmp_path / "trader_collector_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)

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
    init_db()

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_path


def _login_client(trader_collector_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = f"tc_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid


def _collector_offer_visible_text(html: str) -> str:
    cards = re.findall(r'<article class="collector-offer-card[^>]*>.*?</article>', html, re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", card) for card in cards)


def test_trader_hub_renders_collector_market_root(trader_collector_db, monkeypatch):
    client, _uid = _login_client(trader_collector_db, monkeypatch)
    res = client.get("/trader-hub")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert 'id="gc-collector-exchange-panel"' in html
    assert "collector_exchange_title" in html or "Sammler-Markt" in html or "Collector Market" in html
    assert "data-collector-offers-grid" in html
    assert "data-collector-redeem=" in html
    assert "data-collector-specialist-tab=" in html
    assert "collector-offer-progress" in html
    assert 'role="progressbar"' in html
    assert "gc-exchange-panel" in html
    assert "gc-scrapyard-panel" in html
    assert 'id="gc-collector-exchange-state"' in html


def test_trader_hub_only_first_specialist_offers_in_initial_html(trader_collector_db, monkeypatch):
    client, uid = _login_client(trader_collector_db, monkeypatch)
    conn = db()
    assert inventory_schema_ready(conn)
    grant_inventory_item(uid, "fragment_dna_common", 18, conn=conn)
    grant_inventory_item(uid, "fragment_wreck_hull", 20, conn=conn)
    conn.commit()
    conn.close()

    html = client.get("/trader-hub").get_data(as_text=True)
    xeno_offers = [k for k, o in COLLECTOR_OFFERS.items() if o["specialist_key"] == "xenobiologist"]
    scrap_offers = [k for k, o in COLLECTOR_OFFERS.items() if o["specialist_key"] == "scrapmaster"]
    assert any(f'data-offer-key="{k}"' in html for k in xeno_offers)
    assert not any(f'data-offer-key="{k}"' in html for k in scrap_offers)
    assert 'data-collector-active-specialist="xenobiologist"' in html


def test_trader_hub_collector_offers_embedded_from_payload(trader_collector_db, monkeypatch):
    client, uid = _login_client(trader_collector_db, monkeypatch)
    conn = db()
    assert inventory_schema_ready(conn)
    grant_inventory_item(uid, "fragment_dna_common", 18, conn=conn)
    conn.commit()
    conn.close()

    html = client.get("/trader-hub").get_data(as_text=True)
    assert "data-collector-owned=" in html
    assert "disabled" in html
    assert "Research Rush" in html or "Forschungs-Schub" in html


def test_no_raw_offer_keys_as_visible_text(trader_collector_db, monkeypatch):
    client, _uid = _login_client(trader_collector_db, monkeypatch)
    html = client.get("/trader-hub").get_data(as_text=True)
    visible = _collector_offer_visible_text(html)
    for offer_key in COLLECTOR_OFFERS:
        assert offer_key not in visible


def test_no_collector_exchange_nav_route(trader_collector_db, monkeypatch):
    client, _uid = _login_client(trader_collector_db, monkeypatch)
    html = client.get("/trader-hub").get_data(as_text=True)
    assert "/collector-exchange" not in html
    assert 'href="/collector-exchange"' not in html


def test_main_js_collector_redeem_uses_fetch_game_action():
    src = MAIN_JS.read_text(encoding="utf-8")
    assert "/api/collector-exchange/redeem" in src
    assert "GC.fetchGameAction" in src
    assert "applyActionState" in src
    assert "patchCollectorExchangePanel" in src
    assert "initCollectorExchangePanel" in src
    collector_chunk = src.split("initCollectorExchangePanel")[1][:3500]
    assert "location.href" not in collector_chunk
    assert "location.reload" not in collector_chunk


def test_main_js_specialist_tab_switch_renders_without_reload():
    src = MAIN_JS.read_text(encoding="utf-8")
    assert "activateCollectorSpecialistTab" in src
    assert "renderCollectorOffersGrid" in src
    assert "collectorExchangeCache" in src
    assert "data-collector-offers-grid" in src
    tab_fn = src.split("function activateCollectorSpecialistTab")[1].split("function patchCollectorExchangePanel")[0]
    assert "innerHTML = renderCollectorOffersGrid" in tab_fn
    assert "location.reload" not in tab_fn
    assert "location.href" not in tab_fn


def test_main_js_progress_pct_from_server_not_computed():
    src = MAIN_JS.read_text(encoding="utf-8")
    card_fn = src.split("function renderCollectorOfferCard")[1].split("function renderCollectorOffersGrid")[0]
    assert "offer.progress_pct" in card_fn
    assert re.search(r"owned\s*/\s*required|Math\.floor.*owned", card_fn) is None


def test_main_js_sorts_redeemable_offers_first():
    src = MAIN_JS.read_text(encoding="utf-8")
    sort_fn = src.split("function sortCollectorOffers")[1].split("function renderCollectorOfferCard")[0]
    assert "can_redeem" in sort_fn
    assert "progress_pct" in sort_fn


def test_server_sorts_redeemable_offers_first(trader_collector_db):
    conn = db()
    uname = f"sort_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    grant_inventory_item(uid, "fragment_dna_rare", 5, conn=conn)
    conn.commit()
    payload = build_collector_exchange_payload(uid, conn=conn)
    conn.close()

    xeno = next(s for s in payload["specialists"] if s["specialist_key"] == "xenobiologist")
    redeemable = [o for o in xeno["offers"] if o["can_redeem"]]
    assert redeemable
    assert xeno["offers"][0]["can_redeem"] is True
    assert xeno["offers"] == sort_offers_for_display(xeno["offers"])


def test_de_en_locale_keys_for_all_collector_offers():
    for lang in ("en", "de"):
        data = json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))
        for offer_key in COLLECTOR_OFFERS:
            assert f"collector_offer_{offer_key}_title" in data, f"missing title {offer_key} in {lang}"
            assert f"collector_offer_{offer_key}_desc" in data, f"missing desc {offer_key} in {lang}"
            assert f"collector_offer_{offer_key}_reward" in data, f"missing reward {offer_key} in {lang}"


def test_style_has_collector_trader_hub_contract():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "GC-966" in css
    assert ".trader-hub-collector-panel" in css
    assert ".collector-offers-grid" in css
    assert "grid-template-columns: repeat(2" in css


def test_trader_hub_existing_layout_unchanged(trader_collector_db, monkeypatch):
    """Hub still hosts exchange/scrap/collector; GC-Trd-01 switched to top tabs (full middle)."""
    client, _uid = _login_client(trader_collector_db, monkeypatch)
    html = client.get("/trader-hub").get_data(as_text=True)
    assert "trader-hub-panels" in html
    assert 'data-trader-hub-tab="exchange"' in html
    assert 'data-trader-hub-tab="scrapyard"' in html
    assert 'data-trader-hub-tab="collector"' in html
    assert "trader-hub-subpanel" in html
    assert "data-exchange-daily-used" in html
    assert "gc-exchange-panel" in html
    assert "gc-scrapyard-panel" in html
    assert "gc-collector-exchange-panel" in html
