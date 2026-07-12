"""GC-968A — Collector rewards must have real gameplay effects."""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import game.db as dbmod
import game.models as models
from game.collector_catalog import (
    COLLECTOR_LOCKED_REWARD_KEYS,
    COLLECTOR_OFFERS,
    collector_reward_is_redeemable,
    offer_rewards_are_redeemable,
)
from game.collector_exchange import build_collector_exchange_payload, redeem_collector_offer
from game.db import db, begin_write_transaction, commit
from game.effects.effect_resolver import EffectResolver
from game.inventory import grant_inventory_item, inventory_schema_ready
from game.inventory_boosters import activate_inventory_booster, boosters_schema_ready, item_has_implemented_use_effect
from game.inventory_use import use_inventory_item
from game.models import add_research_job, create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def gc968_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc968_test.db"
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


def _uid(conn):
    uname = f"g968_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    return uid


def test_locked_utility_rewards_not_redeemable():
    for key in COLLECTOR_LOCKED_REWARD_KEYS:
        assert collector_reward_is_redeemable(key) is False


def test_time_and_pct_boosters_are_redeemable():
    assert item_has_implemented_use_effect("booster_research_30m")
    assert item_has_implemented_use_effect("booster_research_pct_2_24h")
    assert item_has_implemented_use_effect("booster_energy_surge_24h")
    assert item_has_implemented_use_effect("booster_fleet_speed_25_24h")
    assert collector_reward_is_redeemable("booster_production_25", reward_type="booster")


def test_locked_collector_offers_not_redeemable_even_with_materials(gc968_db):
    conn = db()
    uid = _uid(conn)
    assert inventory_schema_ready(conn)
    grant_inventory_item(uid, "fragment_wreck_hull", 100, conn=conn)
    grant_inventory_item(uid, "fleet_computer", 10, conn=conn)
    grant_inventory_item(uid, "fleet_hyperdrive_module", 30, conn=conn)
    grant_inventory_item(uid, "fragment_alien", 30, conn=conn)
    conn.commit()

    payload = build_collector_exchange_payload(uid, conn=conn)
    locked_keys = {
        "scrap_hull_repair_drones",
        "scrap_computer_fleet_slot",
        "hyper_instant_recall",
        "xeno_alien_scanner",
        "hyper_pirate_scanner",
        "hyper_anomaly_scanner",
    }
    for spec in payload["specialists"]:
        for offer in spec["offers"]:
            if offer["offer_key"] in locked_keys:
                assert offer["rewards_ready"] is False
                assert offer["can_redeem"] is False
    conn.close()


def test_research_pct_booster_increases_research_time_speed(gc968_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    assert boosters_schema_ready(conn)

    begin_write_transaction(conn)
    effect = activate_inventory_booster(uid, "booster_research_pct_2_24h", conn=conn)
    commit(conn)
    assert effect is not None

    resolver = EffectResolver.for_player(uid, conn=conn)
    mods = resolver.get_modifiers()
    assert float(mods.get("research_time_speed") or 1.0) >= 1.019
    conn.close()


def test_research_booster_credits_timekeeper(gc968_db):
    """Legacy time booster credits Timekeeper — no direct queue shift."""
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_research_job(uid, "energy_tech", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_research_30m", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "booster_research_30m", 1, conn=conn)
    commit(conn)
    assert ok, reason

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after == finish_before
    from game.timekeeper import get_balance

    assert get_balance(uid, conn=conn) == 1800
    assert int((result or {}).get("effect", {}).get("seconds_credited") or 0) == 1800
    conn.close()


def test_energy_surge_booster_increases_solar_output(gc968_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "booster_energy_surge_24h", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_energy_surge_24h", 1, conn=conn)
    commit(conn)
    assert ok, reason

    resolver = EffectResolver.for_player(uid, conn=conn)
    mods = resolver.get_modifiers()
    assert float(mods.get("solar_output_factor") or 1.0) >= 1.09
    conn.close()


def test_redeem_locked_offer_rejected(gc968_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "utility_repair_drone", 0, conn=conn)
    grant_inventory_item(uid, "fragment_wreck_hull", 25, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = redeem_collector_offer(
        uid,
        "scrap_hull_repair_drones",
        conn=conn,
        request_id=f"lock-{uuid.uuid4().hex}",
        planet_id=pid,
        player_id=uid,
    )
    commit(conn)
    assert ok is False
    assert reason == "offer_rewards_locked"
    conn.close()


def test_all_active_offers_have_redeemable_rewards_or_locked_flag():
    for offer_key, offer in COLLECTOR_OFFERS.items():
        ready = offer_rewards_are_redeemable(offer)
        if not ready:
            rewards = offer.get("rewards") or []
            has_locked = any(
                str(r.get("reward_key") or "") in COLLECTOR_LOCKED_REWARD_KEYS
                for r in rewards
                if isinstance(r, dict) and r.get("reward_type") not in ("ship_weighted", "item_weighted")
            )
            assert has_locked, offer_key
        else:
            for reward in offer.get("rewards") or []:
                if not isinstance(reward, dict):
                    continue
                rtype = str(reward.get("reward_type") or "")
                if rtype in ("ship_weighted", "item_weighted"):
                    continue
                rkey = str(reward.get("reward_key") or reward.get("ship_key") or "")
                if rtype == "ship":
                    continue
                assert collector_reward_is_redeemable(rkey, reward_type=rtype), (offer_key, rkey)


def test_use_item_api_returns_state(gc968_db, monkeypatch):
    import importlib

    import app as app_module

    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uid = _uid(conn)
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id = ?;", (uid,))
    username = cur.fetchone()["username"]
    grant_inventory_item(uid, "booster_energy_surge_24h", 1, conn=conn)
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": username, "password": "test-pass-123"})
    res = client.post(
        "/api/inventory/use-item",
        json={"item_key": "booster_energy_surge_24h", "amount": 1, "request_id": f"req-{uuid.uuid4().hex}"},
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body.get("ok") is True
    assert "state" in body
