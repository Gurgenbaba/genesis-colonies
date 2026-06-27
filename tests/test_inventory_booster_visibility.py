"""GC-969 — Inventory use vs trade materials vs active duration boosters."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game.collector_catalog import COLLECTOR_LOCKED_REWARD_KEYS
from game.db import begin_write_transaction, commit, db
from game.inventory import build_inventory_state, grant_inventory_item, inventory_schema_ready
from game.inventory_boosters import list_active_boosters
from game.inventory_classification import (
    assert_inventory_classification_consistency,
    classify_inventory_item,
    collector_trade_input_keys,
)
from game.inventory_use import enrich_inventory_item_row, use_inventory_item
from game.models import create_user, ensure_player_and_homeworld, init_db, save_planet_buildings
from game.planet_evolution.repository import get_context_planet


@pytest.fixture
def inv_vis_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inv_vis.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb
    import game.models as models

    gdb._DB_PATH = None
    models.DB_PATH = db_path
    init_db()
    import migrate

    migrate.main()
    yield


def _uid(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"invvis_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_inventory_classification_consistency():
    assert_inventory_classification_consistency()


def test_trade_material_shows_collector_hint_not_usable(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    grant_inventory_item(uid, "fragment_wreck_hull", 5, conn=conn)
    conn.commit()
    row = enrich_inventory_item_row(
        {"item_key": "fragment_wreck_hull", "amount": 5, "rarity": "uncommon", "name_key": "inv_fragment_wreck_hull", "icon": "🛡️"},
        user_id=uid,
        planet_id=int(get_context_planet(uid, conn=conn)["id"]),
        conn=conn,
    )
    assert row["trade_material"] is True
    assert row["usable"] is False
    assert row["use_hint_key"] == "inv_hint_collector_trade"
    conn.close()


def test_duration_booster_usable_and_classified(inv_vis_db):
    row = classify_inventory_item("booster_research_pct_2_24h")
    assert row["usable"] is True
    assert row["duration_effect"] is True
    assert row["instant_use"] is False
    assert row["effect_owner"] == "effect_resolver.research_time_speed"


def test_instant_booster_classified(inv_vis_db):
    row = classify_inventory_item("booster_build_15m")
    assert row["usable"] is True
    assert row["instant_use"] is True
    assert row["duration_effect"] is False


def test_locked_utility_not_usable(inv_vis_db):
    for key in COLLECTOR_LOCKED_REWARD_KEYS:
        row = classify_inventory_item(key)
        assert row["locked_planned"] is True
        assert row["usable"] is False


def test_use_duration_booster_creates_active_entry(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "booster_research_pct_2_24h", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "booster_research_pct_2_24h", 1, conn=conn)
    commit(conn)
    assert ok, reason
    assert int(result.get("consumed") or 0) == 1

    active = list_active_boosters(uid, conn=conn)
    assert any(r["effect_key"] == "research_time_speed" for r in active)
    conn.close()


def test_use_instant_booster_no_active_entry(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    from game.models import add_build_job

    add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_build_15m", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_build_15m", 1, conn=conn)
    commit(conn)
    assert ok, reason
    assert list_active_boosters(uid, conn=conn) == []
    conn.close()


def test_locked_item_use_rejected(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "utility_repair_drone", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "utility_repair_drone", 1, conn=conn)
    commit(conn)
    assert ok is False
    assert reason == "item_locked_planned"
    conn.close()


def test_inventory_state_includes_active_effects(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    begin_write_transaction(conn)
    from game.inventory_boosters import activate_inventory_booster

    activate_inventory_booster(uid, "booster_production_25", conn=conn)
    commit(conn)

    state = build_inventory_state(uid, conn=conn, locale="de")
    effects = (state.get("active_boosters") or {}).get("active_effects") or []
    assert effects
    assert effects[0].get("label")
    assert "booster_" not in effects[0]["label"]
    conn.close()


def test_api_inventory_use_idempotent(inv_vis_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)
    conn = db()
    uid = _uid(conn=conn)
    grant_inventory_item(uid, "resource_pack_ferronit", 1, conn=conn)
    conn.commit()
    conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    body = {
        "item_key": "resource_pack_ferronit",
        "amount": 1,
        "request_id": f"idem-{uuid.uuid4().hex}",
    }
    r1 = client.post("/api/inventory/use", json=body)
    r2 = client.post("/api/inventory/use", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json().get("ok") is True
    assert r2.get_json().get("ok") is True
    assert r1.get_json().get("state") is not None
    assert r2.get_json().get("inventory") is not None


def test_booster_items_not_collector_inputs():
    trade = collector_trade_input_keys()
    for key in (
        "booster_production_25",
        "booster_research_pct_2_24h",
        "booster_build_15m",
        "booster_energy_surge_24h",
    ):
        assert key not in trade
