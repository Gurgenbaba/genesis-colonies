"""Full-finish integration tests — Collector Exchange + Trader Hub + honest rewards."""

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

import game.db as dbmod
import game.models as models
from game.collector_catalog import COLLECTOR_LOCKED_REWARD_KEYS, COLLECTOR_OFFERS, offer_rewards_are_redeemable
from game.collector_exchange import build_collector_exchange_payload, redeem_collector_offer
from game.db import begin_write_transaction, commit, db
from game.inventory import grant_inventory_item, inventory_amount, inventory_schema_ready
from game.inventory_boosters import item_has_implemented_use_effect
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"
MAIN_JS = ROOT / "static" / "main.js"
LOCALES = ROOT / "locales"


@pytest.fixture
def collector_full_db(tmp_path, monkeypatch):
    db_path = tmp_path / "collector_full.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)

    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_path)
    subprocess.run([sys.executable, str(MIGRATE_SCRIPT)], cwd=str(ROOT), check=True, env=env)
    init_db()
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    yield db_path


def _login(monkeypatch, collector_full_db):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import app as app_module

    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = f"full_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid, app_module


def test_game_state_includes_collector_and_active_boosters(collector_full_db, monkeypatch):
    client, uid, _app = _login(monkeypatch, collector_full_db)
    conn = db()
    grant_inventory_item(uid, "booster_energy_surge_24h", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.get("/api/game-state?include_panel=1&panel_page=trader_hub")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("collector_exchange", {}).get("ready") is True
    assert "specialists" in data["collector_exchange"]
    assert "active_boosters" in data
    assert isinstance(data["active_boosters"].get("active"), list)
    assert isinstance(data["active_boosters"].get("active_effects"), list)


def test_redeem_idempotent(collector_full_db, monkeypatch):
    client, uid, app_module = _login(monkeypatch, collector_full_db)
    conn = db()
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    conn.commit()
    conn.close()

    rid = f"idem-{uuid.uuid4().hex}"
    body = {"offer_key": "xeno_dna_common_research_booster", "request_id": rid}
    r1 = client.post("/api/collector-exchange/redeem", json=body)
    r2 = client.post("/api/collector-exchange/redeem", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json().get("ok") is True
    assert r2.get_json().get("ok") is True

    conn = db()
    owned = inventory_amount(uid, "booster_research_30m", conn=conn)
    conn.close()
    assert owned == 1


def test_lifetime_stats_never_decrease_on_redeem(collector_full_db, monkeypatch):
    client, uid, _app = _login(monkeypatch, collector_full_db)
    conn = db()
    grant_inventory_item(uid, "fragment_dna_common", 100, conn=conn)
    conn.commit()
    cur = conn.cursor()
    cur.execute(
        "SELECT lifetime_acquired, lifetime_redeemed FROM collector_lifetime_stats WHERE user_id=? AND item_key=?;",
        (uid, "fragment_dna_common"),
    )
    before = cur.fetchone()
    before_acq = int(before["lifetime_acquired"] or 0) if before else 0
    before_red = int(before["lifetime_redeemed"] or 0) if before else 0
    conn.close()

    client.post(
        "/api/collector-exchange/redeem",
        json={"offer_key": "xeno_dna_common_research_booster", "request_id": f"life-{uuid.uuid4().hex}"},
    )

    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT lifetime_acquired, lifetime_redeemed FROM collector_lifetime_stats WHERE user_id=? AND item_key=?;",
        (uid, "fragment_dna_common"),
    )
    after = cur.fetchone()
    assert int(after["lifetime_acquired"] or 0) >= before_acq
    assert int(after["lifetime_redeemed"] or 0) >= before_red + 50
    conn.close()


def test_all_locale_files_have_collector_offer_keys(collector_full_db):
    for path in sorted(LOCALES.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for offer_key in COLLECTOR_OFFERS:
            for suffix in ("title", "desc", "reward"):
                key = f"collector_offer_{offer_key}_{suffix}"
                assert key in data and str(data[key]).strip(), f"{path.name} missing {key}"


def test_no_raw_keys_in_trader_hub_grid(collector_full_db, monkeypatch):
    client, _uid, _app = _login(monkeypatch, collector_full_db)
    html = client.get("/trader-hub").get_data(as_text=True)
    cards = re.findall(r'<article class="collector-offer-card[^>]*>.*?</article>', html, re.S)
    visible = " ".join(re.sub(r"<[^>]+>", " ", c) for c in cards)
    for offer_key in COLLECTOR_OFFERS:
        assert offer_key not in visible
    assert "/collector-exchange" not in html
    assert "data-collector-offers-grid" in html


def test_main_js_no_reload_in_collector_flow():
    src = MAIN_JS.read_text(encoding="utf-8")
    idx = src.find("  function initCollectorExchangePanel() {")
    assert idx >= 0
    chunk = src[idx : idx + 4000]
    assert "location.reload" not in chunk
    assert "location.href" not in chunk
    assert "applyActionState" in chunk


def test_every_active_offer_passes_reward_audit():
    locked_offers = {
        "scrap_hull_repair_drones",
        "scrap_computer_fleet_slot",
        "hyper_instant_recall",
        "xeno_alien_scanner",
        "hyper_pirate_scanner",
        "hyper_anomaly_scanner",
    }
    for offer_key, offer in COLLECTOR_OFFERS.items():
        ready = offer_rewards_are_redeemable(offer)
        if offer_key in locked_offers:
            assert ready is False
        else:
            assert ready is True, offer_key
            for reward in offer.get("rewards") or []:
                if str(reward.get("reward_type")) in ("ship_weighted", "item_weighted"):
                    continue
                rkey = str(reward.get("reward_key") or "")
                if rkey in COLLECTOR_LOCKED_REWARD_KEYS:
                    pytest.fail(f"locked reward in active offer {offer_key}: {rkey}")
                if rkey and reward.get("reward_type") in ("item", "booster"):
                    assert item_has_implemented_use_effect(rkey) or rkey in {
                        "expo_star_chart",
                        "dna_core_common",
                    }, (offer_key, rkey)
