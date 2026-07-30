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


def test_production_booster_duration_stacks_on_reuse(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    now = 1_700_000_000.0
    from game.inventory_boosters import activate_inventory_booster, list_active_boosters

    begin_write_transaction(conn)
    first = activate_inventory_booster(uid, "booster_production_25", conn=conn, now=now)
    assert first is not None
    first_expires = float(first["expires_at"])
    # Catalog duration is 1h — redeem again with half remaining.
    mid = now + 30 * 60
    second = activate_inventory_booster(uid, "booster_production_25", conn=conn, now=mid)
    commit(conn)
    assert second is not None
    expected = first_expires + 3600
    assert abs(float(second["expires_at"]) - expected) < 1.0
    assert int(second.get("remaining_seconds") or 0) == int(expected - mid)
    active = list_active_boosters(uid, conn=conn, now=mid)
    metal = next(r for r in active if r["effect_key"] == "metal_prod_factor")
    assert abs(float(metal["expires_at"]) - expected) < 1.0
    assert float(metal["multiplier"]) == 1.25
    conn.close()


def test_production_booster_tier_ladder_25_then_50(inv_vis_db):
    """GC-PERF-BOOST-001: 25%+50% stack to 75%; after 50% expires, 25% remains."""
    import time as time_mod

    conn = db()
    uid = _uid(conn=conn)
    # Use wall-clock base so HUD enrich (EffectResolver) purge does not wipe rows.
    now = float(time_mod.time())
    from game.inventory_boosters import (
        activate_inventory_booster,
        build_active_effects_for_hud,
        get_active_booster_multipliers,
        list_active_boosters,
    )

    begin_write_transaction(conn)
    # 2×25% → 25% lasting 2h; then 50% for 1h alongside.
    activate_inventory_booster(uid, "booster_production_25", conn=conn, now=now)
    activate_inventory_booster(uid, "booster_production_25", conn=conn, now=now + 30 * 60)
    activate_inventory_booster(uid, "booster_production_50", conn=conn, now=now)
    commit(conn)

    mults = get_active_booster_multipliers(uid, conn=conn, now=now)
    assert abs(float(mults.get("metal_prod_factor") or 0) - 1.75) < 1e-9
    assert abs(float(mults.get("crystal_prod_factor") or 0) - 1.75) < 1e-9
    assert abs(float(mults.get("fuel_prod_factor") or 0) - 1.75) < 1e-9

    active = list_active_boosters(uid, conn=conn, now=now)
    metal_tiers = [r for r in active if r["effect_key"] == "metal_prod_factor"]
    assert len(metal_tiers) == 2
    by_src = {r["source_item_key"]: r for r in metal_tiers}
    assert abs(float(by_src["booster_production_50"]["expires_at"]) - (now + 3600)) < 2.0
    assert abs(float(by_src["booster_production_25"]["expires_at"]) - (now + 7200)) < 2.0

    hud = build_active_effects_for_hud(uid, conn=conn, locale="en", now=now)
    chip = next(e for e in hud if e.get("hud_chip_only") or e.get("key") == "production")
    assert int(chip.get("effect_summary_params", {}).get("pct") or 0) == 75
    assert chip.get("stack_aggregate") is True
    list_rows = [e for e in hud if e.get("hud_list_only")]
    assert len(list_rows) == 2
    pcts = sorted(int(e.get("effect_summary_params", {}).get("pct") or 0) for e in list_rows)
    assert pcts == [25, 50]
    assert not any(e.get("tier_standby") for e in list_rows)
    assert int(chip.get("remaining_seconds") or 0) <= 3600 + 2
    assert int(chip.get("remaining_seconds") or 0) >= 3600 - 5

    after_50 = now + 3600 + 5
    mults_after = get_active_booster_multipliers(uid, conn=conn, now=after_50)
    assert abs(float(mults_after.get("metal_prod_factor") or 0) - 1.25) < 1e-9
    hud_after = build_active_effects_for_hud(uid, conn=conn, locale="en", now=after_50)
    chip_after = next(
        e for e in hud_after if e.get("hud_chip_only") or e.get("key") == "production"
    )
    assert int(chip_after.get("effect_summary_params", {}).get("pct") or 0) == 25
    assert int(chip_after.get("remaining_seconds") or 0) >= 3500
    conn.close()


def test_research_pct_booster_duration_stacks_on_reuse(inv_vis_db):
    conn = db()
    uid = _uid(conn=conn)
    now = 1_700_000_000.0
    from game.inventory_boosters import activate_inventory_booster

    begin_write_transaction(conn)
    first = activate_inventory_booster(uid, "booster_research_pct_2_24h", conn=conn, now=now)
    mid = now + 6 * 3600
    second = activate_inventory_booster(uid, "booster_research_pct_2_24h", conn=conn, now=mid)
    commit(conn)
    assert first and second
    assert abs(float(second["expires_at"]) - (float(first["expires_at"]) + 24 * 3600)) < 1.0
    assert int(second.get("remaining_seconds") or 0) >= 24 * 3600
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
