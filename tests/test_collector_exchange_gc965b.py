"""GC-965B — Collector Exchange redeem, lifetime stats, idempotency."""

from __future__ import annotations

import importlib
import json
import os
import random
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import app as app_module
import game.db as dbmod
import game.models as models
from game.collector_exchange import (
    build_collector_exchange_payload,
    get_lifetime_stats,
    redeem_collector_offer,
    record_lifetime_acquired,
    resolve_offer_grants,
)
from game.db import db
from game.fleet import get_planet_ships
from game.inventory import grant_inventory_item, inventory_amount, inventory_schema_ready, run_inventory_mutation
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.planet_evolution.repository import get_context_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def collector_redeem_db(tmp_path, monkeypatch):
    db_path = tmp_path / "collector_redeem_test.db"
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


def _login_client(collector_redeem_db, monkeypatch):
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    app_module.app.config["WTF_CSRF_ENABLED"] = False

    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid


def _planet_id(uid: int) -> int:
    conn = db()
    try:
        planet = get_context_planet(uid, conn=conn)
        return int(planet["id"])
    finally:
        conn.close()


def test_redeem_happy_path_consumes_and_grants(collector_redeem_db):
    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(get_context_planet(uid, conn=conn)["id"])

    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    conn.commit()

    ok, reason, result = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "xeno_dna_common_research_booster",
            conn=c,
            planet_id=planet_id,
            player_id=uid,
            rng=random.Random(42),
        )
    )
    conn.close()

    assert ok is True, reason
    assert result is not None
    assert result["input_key"] == "fragment_dna_common"
    assert any(r.get("reward_key") == "booster_research_30m" for r in result["rewards"])

    conn = db()
    assert inventory_amount(uid, "fragment_dna_common", conn=conn) == 0
    assert inventory_amount(uid, "booster_research_30m", conn=conn) == 1
    stats = get_lifetime_stats(uid, conn=conn)
    assert stats["fragment_dna_common"]["lifetime_redeemed"] == 50
    assert stats["fragment_dna_common"]["lifetime_acquired"] >= 50
    assert stats["booster_research_30m"]["lifetime_acquired"] == 1
    conn.close()


def test_redeem_insufficient_items(collector_redeem_db):
    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(get_context_planet(uid, conn=conn)["id"])

    grant_inventory_item(uid, "fragment_dna_common", 10, conn=conn)
    conn.commit()

    ok, reason, result = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "xeno_dna_common_research_booster",
            conn=c,
            planet_id=planet_id,
            player_id=uid,
        )
    )
    conn.close()

    assert ok is False
    assert reason == "insufficient_items"
    conn = db()
    assert inventory_amount(uid, "fragment_dna_common", conn=conn) == 10
    conn.close()


def test_lifetime_acquired_not_decreased_on_redeem(collector_redeem_db):
    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(get_context_planet(uid, conn=conn)["id"])

    grant_inventory_item(uid, "fragment_wreck_hull", 20, conn=conn)
    conn.commit()
    acquired_before = get_lifetime_stats(uid, conn=conn)["fragment_wreck_hull"]["lifetime_acquired"]

    ok, reason, _ = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "scrap_hull_shipyard_15m",
            conn=c,
            planet_id=planet_id,
            player_id=uid,
        )
    )
    assert ok, reason
    stats = get_lifetime_stats(uid, conn=conn)
    assert stats["fragment_wreck_hull"]["lifetime_acquired"] == acquired_before
    assert stats["fragment_wreck_hull"]["lifetime_redeemed"] == 20
    conn.close()


def test_redeem_ship_weighted_offer(collector_redeem_db):
    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(get_context_planet(uid, conn=conn)["id"])

    grant_inventory_item(uid, "fragment_wreck_hull", 20, conn=conn)
    conn.commit()

    ok, reason, result = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "scrap_hull_random_ship_small",
            conn=c,
            planet_id=planet_id,
            player_id=uid,
            rng=random.Random(1),
        )
    )
    assert ok, reason
    assert result is not None
    ship_reward = result["rewards"][0]
    assert ship_reward["reward_type"] == "ship"
    assert ship_reward["reward_key"] in ("spark_drone", "mule_courier")

    ships = get_planet_ships(planet_id, conn=conn)
    assert int(ships.get(ship_reward["reward_key"]) or 0) >= int(ship_reward["amount"])
    conn.close()


def test_redeem_idempotent_request_id(collector_redeem_db):
    conn = db()
    uname = f"cr_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    planet_id = int(get_context_planet(uid, conn=conn)["id"])

    grant_inventory_item(uid, "fragment_dna_common", 100, conn=conn)
    conn.commit()
    conn.close()

    rid = f"req-{uuid.uuid4().hex}"

    ok1, _, r1 = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "xeno_dna_common_research_booster",
            conn=c,
            request_id=rid,
            planet_id=planet_id,
            player_id=uid,
        )
    )
    assert ok1 is True

    ok2, _, r2 = run_inventory_mutation(
        lambda c: redeem_collector_offer(
            uid,
            "xeno_dna_common_research_booster",
            conn=c,
            request_id=rid,
            planet_id=planet_id,
            player_id=uid,
        )
    )
    assert ok2 is True
    assert r2.get("idempotent_replay") is True

    conn = db()
    assert inventory_amount(uid, "fragment_dna_common", conn=conn) == 50
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM collector_exchange_redemptions WHERE user_id = ? AND request_id = ?;",
        (uid, rid),
    )
    assert int(cur.fetchone()["c"]) == 1
    conn.close()


def test_api_collector_redeem_returns_state(collector_redeem_db, monkeypatch):
    client, uid = _login_client(collector_redeem_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/collector-exchange/redeem",
        json={
            "offer_key": "xeno_dna_common_dna_capsule",
            "request_id": f"api-{uuid.uuid4().hex}",
        },
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["ok"] is True
    assert body["reason"] == "collector_redeem_ok"
    assert "state" in body
    assert body["state"]["collector_exchange"]["ready"] is True
    specialists = body["state"]["collector_exchange"]["specialists"]
    xeno = next(s for s in specialists if s["specialist_key"] == "xenobiologist")
    dna_offer = next(o for o in xeno["offers"] if o["offer_key"] == "xeno_dna_common_dna_capsule")
    assert dna_offer["owned"] == 0
    assert dna_offer["can_redeem"] is False


def test_game_state_includes_collector_exchange(collector_redeem_db, monkeypatch):
    client, _uid = _login_client(collector_redeem_db, monkeypatch)
    res = client.get("/api/game-state?include_panel=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "collector_exchange" in data
    assert data["collector_exchange"].get("ready") is True
    assert len(data["collector_exchange"].get("specialists") or []) == 4


def test_resolve_offer_grants_weighted_item_pool():
    offer = {
        "rewards": [
            {
                "reward_type": "item_weighted",
                "pool": [
                    {"weight": 1, "reward_key": "research_data_energy", "amount": 1},
                    {"weight": 1, "reward_key": "research_data_mining", "amount": 1},
                ],
            }
        ]
    }
    grants = resolve_offer_grants(offer, rng=random.Random(0))
    assert len(grants) == 1
    assert grants[0]["reward_key"] in ("research_data_energy", "research_data_mining")
