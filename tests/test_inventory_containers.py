"""GC-540 — Container inventory and loot system."""

from __future__ import annotations

import importlib
import os
import random
import time
import uuid

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db, rollback
from game.inventory import (
    CONTAINER_KEYS,
    basic_container_cooldown_remaining,
    build_container_catalog,
    build_inventory_state,
    grant_inventory_item,
    inventory_schema_ready,
    open_containers,
)
from game.inventory_catalog import CONTAINER_BASIC_COOLDOWN_SEC, CONTAINER_BASIC_KEY
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_idempotent_action,
    get_planets_by_player,
    init_db,
    save_idempotent_action,
)
from game.planet_evolution.repository import get_context_planet


@pytest.fixture
def inventory_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inventory_containers.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"inv_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="LootTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _login_client(inventory_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid, app_module


def _planet_resources(conn, planet_id: int):
    row = conn.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    return float(row["metal"]), float(row["crystal"]), float(row["fuel_cells"] or 0)


def test_inventory_schema_ready(inventory_db):
    conn = db()
    assert inventory_schema_ready(conn)
    conn.close()


def test_container_debited_and_loot_credited(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    metal_before, crystal_before, fuel_before = _planet_resources(conn, pid)

    grant_inventory_item(uid, "container_basic", 2, conn=conn)
    begin_write_transaction(conn)
    rng = random.Random(42)
    ok, reason, result = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=rng)
    assert ok, reason
    commit(conn)

    owned = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "container_basic"),
    ).fetchone()
    assert owned and int(owned["amount"]) == 1

    assert result and result["rewards"]
    assert any(int(r.get("amount") or 0) > 0 for r in result["rewards"])
    metal_after, crystal_after, fuel_after = _planet_resources(conn, pid)
    ships_changed = any(r.get("reward_type") == "ship" for r in result["rewards"])
    defense_changed = any(r.get("reward_type") == "defense" for r in result["rewards"])
    items_changed = any(r.get("reward_type") in ("item", "booster") for r in result["rewards"])
    resources_changed = (
        metal_after > metal_before
        or crystal_after > crystal_before
        or fuel_after > fuel_before
    )
    assert resources_changed or ships_changed or defense_changed or items_changed

    log_count = conn.execute(
        "SELECT COUNT(*) AS c FROM container_open_log WHERE user_id = ?;",
        (uid,),
    ).fetchone()["c"]
    assert int(log_count) == 1
    conn.close()


def test_resources_land_on_context_planet(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])

    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    begin_write_transaction(conn)
    ok, reason, result = open_containers(
        uid,
        pid,
        "container_basic",
        1,
        conn=conn,
        rng=random.Random(7),
    )
    assert ok, reason
    commit(conn)

    rewards = (result or {}).get("rewards") or []
    resource_total = sum(int(r.get("amount") or 0) for r in rewards if r.get("reward_type") == "resource")
    assert resource_total > 0

    row = conn.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (pid,)).fetchone()
    assert float(row["metal"]) + float(row["crystal"]) + float(row["fuel_cells"] or 0) >= resource_total
    conn.close()


def test_invalid_container_rejected(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_unknown", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "invalid_container"
    conn.close()


def test_open_without_container_rejected(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_basic", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "insufficient_containers"
    conn.close()


def test_amount_above_owned_rejected(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_rare", 2, conn=conn)
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_rare", 3, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "insufficient_containers"
    conn.close()


def test_amount_above_max_rejected(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 20, conn=conn)
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_basic", 11, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "amount_too_high"
    conn.close()


def test_idempotency_prevents_double_open(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()
    conn.close()

    body = {
        "item_key": "container_basic",
        "amount": 1,
        "request_id": f"inv-test-{uuid.uuid4().hex}",
    }
    r1 = client.post("/api/inventory/open-container", json=body)
    r2 = client.post("/api/inventory/open-container", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    j1 = r1.get_json()
    j2 = r2.get_json()
    assert j1["ok"] is True
    assert j2["ok"] is True
    assert j1["rewards"] == j2["rewards"]

    conn = db()
    owned = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "container_basic"),
    ).fetchone()
    assert owned is None
    log_count = conn.execute(
        "SELECT COUNT(*) AS c FROM container_open_log WHERE user_id = ?;",
        (uid,),
    ).fetchone()["c"]
    assert int(log_count) == 1
    conn.close()


def test_api_inventory_state(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_rare", 3, conn=conn)
    conn.commit()
    conn.close()

    res = client.get("/api/inventory/state")
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    containers = data["inventory"]["containers"]
    assert any(c["item_key"] == "container_rare" and c["amount"] == 3 for c in containers)


def test_inventory_page_loads(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.get("/inventory")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "inventory-page" in body
    assert "inventory-loot-card" in body
    assert "lootboxes/Basic_Container.png" in body
    assert 'data-inventory-container="container_basic"' in body


def test_container_catalog_shows_all_with_zero_by_default(inventory_db):
    catalog = build_container_catalog()
    assert len(catalog) == len(CONTAINER_KEYS)
    assert all(c["amount"] == 0 and not c["owned"] for c in catalog)
    assert all(c.get("image", "").startswith("img/lootboxes/") for c in catalog)


def test_all_container_keys_have_pools():
    for key in CONTAINER_KEYS:
        from game.inventory import LOOT_POOLS

        assert key in LOOT_POOLS
        assert LOOT_POOLS[key]


def test_basic_container_24h_cooldown(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 3, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok1, reason1, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(99))
    assert ok1, reason1
    commit(conn)

    begin_write_transaction(conn)
    ok2, reason2, payload = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(100))
    rollback(conn)
    assert not ok2
    assert reason2 == "container_cooldown"
    assert int((payload or {}).get("cooldown_seconds") or 0) > 0

    assert basic_container_cooldown_remaining(uid, conn=conn) > 0
    state = build_inventory_state(uid, conn=conn)
    basic = next(c for c in state["containers"] if c["item_key"] == CONTAINER_BASIC_KEY)
    assert basic["open_blocked"] is True
    assert basic["max_open_amount"] == 1
    conn.close()


def test_basic_container_cooldown_expires(inventory_db, monkeypatch):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 2, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok1, _, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(11))
    assert ok1
    commit(conn)

    future = time.time() + CONTAINER_BASIC_COOLDOWN_SEC + 5
    assert basic_container_cooldown_remaining(uid, conn=conn, now=future) == 0
    monkeypatch.setattr("game.inventory.time.time", lambda: future)

    begin_write_transaction(conn)
    ok2, reason2, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(12))
    assert ok2, reason2
    commit(conn)
    conn.close()


def test_basic_container_rejects_multi_open(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 5, conn=conn)
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_basic", 2, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "basic_open_once"
    conn.close()


def test_open_grants_ships_to_context_planet(inventory_db, monkeypatch):
    from game import inventory_loot

    monkeypatch.setitem(
        inventory_loot.LOOT_POOLS,
        "container_basic",
        [
            {
                "weight": 100,
                "reward_type": "ship",
                "reward_key": "spark_drone",
                "min_amount": 3,
                "max_amount": 3,
            }
        ],
    )
    from game.fleet import get_planet_ships

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(1))
    assert ok, reason
    commit(conn)
    ships = get_planet_ships(pid, conn=conn)
    assert int(ships.get("spark_drone") or 0) == 3
    conn.close()


def test_open_grants_defense_to_context_planet(inventory_db, monkeypatch):
    from game import inventory_loot

    monkeypatch.setitem(
        inventory_loot.LOOT_POOLS,
        "container_military_cache",
        [
            {
                "weight": 100,
                "reward_type": "defense",
                "reward_key": "sentinel_turret",
                "min_amount": 5,
                "max_amount": 5,
            }
        ],
    )
    from game.models import get_planet_defense

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_military_cache", 1, conn=conn)
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_military_cache", 1, conn=conn, rng=random.Random(2))
    assert ok, reason
    commit(conn)
    defense = get_planet_defense(pid, conn=conn)
    assert int(defense.get("sentinel_turret") or 0) == 5
    conn.close()


def test_save_idempotent_action_roundtrip(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    conn.close()
    rid = f"unit-{uuid.uuid4().hex}"
    payload = {"ok": True, "rewards": [], "inventory": {}}
    save_idempotent_action(uid, rid, payload)
    cached = get_idempotent_action(uid, rid)
    assert cached == payload
