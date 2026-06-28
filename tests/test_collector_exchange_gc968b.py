"""GC-968B — Booster formula wiring, HUD game-state, empire parity."""

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
from game.collector_catalog import COLLECTOR_LOCKED_REWARD_KEYS, collector_reward_is_redeemable
from game.db import db, begin_write_transaction, commit
from game.effects.effect_resolver import EffectResolver
from game.empire_page import build_empire_context
from game.inventory import grant_inventory_item
from game.inventory_boosters import (
    BOOSTER_AUDIT,
    activate_inventory_booster,
    boosters_schema_ready,
    build_active_effects_for_hud,
    build_inventory_boosters_state,
    item_has_implemented_use_effect,
)
from game.inventory_use import use_inventory_item
from game.models import add_build_job, add_research_job, create_user, ensure_player_and_homeworld, init_db, save_planet_buildings
from game.planet_evolution.repository import get_context_planet

ROOT = Path(__file__).resolve().parent.parent
MIGRATE_SCRIPT = ROOT / "migrate.py"


@pytest.fixture
def gc968b_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc968b_test.db"
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
    uname = f"g968b_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    return uid


def test_production_boosters_use_formula_not_instant_grant():
    assert item_has_implemented_use_effect("booster_production_25")
    assert item_has_implemented_use_effect("booster_production_50")
    assert collector_reward_is_redeemable("booster_production_25", reward_type="booster")
    assert BOOSTER_AUDIT["booster_production_25"] == "active_real_effect"


def test_research_pct_reduces_new_job_duration_not_running_queue(gc968b_db):
    conn = db()
    uid = _uid(conn)
    now = time.time()
    add_research_job(uid, "energy_tech", now - 5, now + 3600, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )

    resolver_base = EffectResolver.for_player(uid, conn=conn)
    duration_base = resolver_base.get_research_time_seconds("energy_tech", 1)

    begin_write_transaction(conn)
    activate_inventory_booster(uid, "booster_research_pct_2_24h", conn=conn)
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after == finish_before

    resolver_boost = EffectResolver.for_player(uid, conn=conn)
    duration_boost = resolver_boost.get_research_time_seconds("energy_tech", 1)
    assert duration_boost < duration_base
    conn.close()


def test_production_pct_booster_increases_production_per_hour(gc968b_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    conn.close()

    save_planet_buildings(pid, {"metal_mine": 8, "solar_plant": 10, "crystal_mine": 4})

    conn = db()
    resolver_before = EffectResolver.for_player(uid, conn=conn)
    energy_total, energy_used = resolver_before.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    prod_before = resolver_before.get_building_production_per_hour(ratio)
    metal_before = int(prod_before.get("metal_mine") or 0)

    begin_write_transaction(conn)
    activate_inventory_booster(uid, "booster_production_50", conn=conn)
    commit(conn)

    resolver_after = EffectResolver.for_player(uid, conn=conn)
    energy_total, energy_used = resolver_after.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    prod_after = resolver_after.get_building_production_per_hour(ratio)
    metal_after = int(prod_after.get("metal_mine") or 0)
    assert metal_after > metal_before
    conn.close()


def test_energy_booster_affects_solar_and_energy_ratio(gc968b_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    conn.close()

    save_planet_buildings(pid, {"metal_mine": 10, "solar_plant": 5})

    conn = db()
    grant_inventory_item(uid, "booster_energy_surge_24h", 1, conn=conn)
    conn.commit()

    resolver_before = EffectResolver.for_player(uid, conn=conn)
    total_before, used_before = resolver_before.compute_energy()
    ratio_before = EffectResolver.energy_ratio(total_before, used_before)

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_energy_surge_24h", 1, conn=conn)
    commit(conn)
    assert ok, reason

    resolver_after = EffectResolver.for_player(uid, conn=conn)
    total_after, used_after = resolver_after.compute_energy()
    ratio_after = EffectResolver.energy_ratio(total_after, used_after)
    assert total_after > total_before
    assert ratio_after >= ratio_before
    conn.close()


def test_empire_production_reflects_active_production_booster(gc968b_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    conn.close()

    save_planet_buildings(pid, {"metal_mine": 8, "solar_plant": 10})

    conn = db()
    ctx_before = build_empire_context(uid)
    metal_before = int(ctx_before["production"]["metal"])

    begin_write_transaction(conn)
    activate_inventory_booster(uid, "booster_production_25", conn=conn)
    commit(conn)

    ctx_after = build_empire_context(uid)
    assert int(ctx_after["production"]["metal"]) > metal_before
    conn.close()


def test_game_state_active_effects_hud_payload(gc968b_db, monkeypatch):
    conn = db()
    uid = _uid(conn)
    begin_write_transaction(conn)
    activate_inventory_booster(uid, "booster_research_pct_2_24h", conn=conn)
    commit(conn)

    state = build_inventory_boosters_state(uid, conn=conn, locale="de")
    effects = state.get("active_effects") or []
    assert effects
    row = effects[0]
    for field in (
        "key",
        "label",
        "effect_summary",
        "expires_at",
        "remaining_seconds",
        "affected_domain",
    ):
        assert field in row
    assert "booster_" not in row["label"]
    assert row["affected_domain"] == "research"
    assert row.get("applies_to") == "new_jobs_only"
    assert row.get("note")
    conn.close()

    dbmod.DB_PATH = gc968b_db
    models.DB_PATH = gc968b_db
    import app as app_module

    importlib.reload(app_module)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.get("/api/game-state?include_panel=1")
    assert res.status_code == 200
    data = res.get_json()
    assert data.get("ok") is not False
    hud = (data.get("active_boosters") or {}).get("active_effects") or []
    assert hud
    assert hud[0].get("label")


def test_locked_rewards_still_not_redeemable():
    for key in COLLECTOR_LOCKED_REWARD_KEYS:
        assert collector_reward_is_redeemable(key) is False


def test_build_time_booster_still_queue_shift(gc968b_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_build_15m", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_time"]
    )

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_build_15m", 1, conn=conn)
    commit(conn)
    assert ok, reason

    finish_after = float(
        conn.execute(
            "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_time"]
    )
    assert finish_after < finish_before
    conn.close()


def test_hud_builder_groups_production_factors(gc968b_db):
    conn = db()
    uid = _uid(conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    conn.close()

    save_planet_buildings(pid, {"metal_mine": 8, "crystal_mine": 6, "solar_plant": 10})

    conn = db()
    begin_write_transaction(conn)
    activate_inventory_booster(uid, "booster_production_25", conn=conn)
    commit(conn)

    effects = build_active_effects_for_hud(uid, conn=conn, locale="en")
    prod_rows = [e for e in effects if e.get("affected_domain") == "production"]
    assert len(prod_rows) == 1
    assert prod_rows[0].get("key") == "production"
    impacts = prod_rows[0].get("resource_impacts") or {}
    assert int((impacts.get("metal") or {}).get("delta_per_hour") or 0) > 0
    assert (impacts.get("metal") or {}).get("impact_summary")
    conn.close()
