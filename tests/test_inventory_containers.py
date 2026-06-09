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


def test_loot_drops_reference_matches_pools(inventory_db):
    from game.inventory import build_loot_drops_reference
    from game.inventory_loot import LOOT_POOLS

    rows = build_loot_drops_reference()
    assert len(rows) == len(CONTAINER_KEYS)
    for row in rows:
        assert row["item_key"] in LOOT_POOLS
        assert len(row["drops"]) == len(LOOT_POOLS[row["item_key"]])
        assert row["drops"][0]["amount_label"]
        assert row["drops"][0]["weight_pct"] > 0


def test_inventory_page_shows_loot_drops(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    res = client.get("/inventory")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "inventory-loot-drops" in body
    assert "inventory-drops-row" in body
    assert "inv_loot_drops_title" in body or "Mögliche Drops" in body or "Possible drops" in body


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


def test_basic_free_daily_open_without_stock(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    begin_write_transaction(conn)
    ok, reason, result = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(5))
    assert ok, reason
    commit(conn)

    assert result and result["rewards"]
    owned = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, CONTAINER_BASIC_KEY),
    ).fetchone()
    assert owned is None

    state = build_inventory_state(uid, conn=conn)
    basic = next(c for c in state["containers"] if c["item_key"] == CONTAINER_BASIC_KEY)
    assert basic["open_blocked"] is True
    assert basic["cooldown_active"] is True
    assert int(basic["cooldown_seconds"]) > 0
    conn.close()


def test_open_without_container_rejected_for_non_basic(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    begin_write_transaction(conn)
    ok, reason, _ = open_containers(uid, pid, "container_rare", 1, conn=conn)
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


def test_basic_container_owned_bypasses_cooldown(inventory_db):
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
    ok2, reason2, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(100))
    assert ok2, reason2
    commit(conn)

    assert basic_container_cooldown_remaining(uid, conn=conn) > 0
    owned = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, CONTAINER_BASIC_KEY),
    ).fetchone()
    assert owned and int(owned["amount"]) == 1

    state = build_inventory_state(uid, conn=conn)
    basic = next(c for c in state["containers"] if c["item_key"] == CONTAINER_BASIC_KEY)
    assert basic["open_blocked"] is False
    assert basic["cooldown_active"] is True
    assert int(basic["cooldown_seconds"]) > 0
    assert basic["max_open_amount"] == 1
    conn.close()


def test_basic_container_cooldown_without_stock(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok1, reason1, _ = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(88))
    assert ok1, reason1
    commit(conn)

    begin_write_transaction(conn)
    ok2, reason2, payload = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=random.Random(89))
    rollback(conn)
    assert not ok2
    assert reason2 == "container_cooldown"
    assert int((payload or {}).get("cooldown_seconds") or 0) > 0

    state = build_inventory_state(uid, conn=conn)
    basic = next(c for c in state["containers"] if c["item_key"] == CONTAINER_BASIC_KEY)
    assert basic["amount"] == 0
    assert basic["open_blocked"] is True
    assert basic["cooldown_active"] is True
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


def _preview_matches_winning(preview_entry, winning_reward):
    assert preview_entry["key"] == winning_reward["preview_key"]
    assert int(preview_entry["amount"]) == int(winning_reward["amount"])
    assert preview_entry["rarity"] == winning_reward["rarity"]
    assert preview_entry["type"] == winning_reward["type"]
    assert preview_entry["icon"] == winning_reward["icon"]


def test_open_container_returns_roll_preview(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_rare", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_rare",
            "amount": 1,
            "request_id": f"roll-preview-{uuid.uuid4().hex}",
        },
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "roll_preview" in data
    assert len(data["roll_preview"]) >= 20


    assert "roll_preview" in data
    assert len(data["roll_preview"]) >= 30


def test_open_container_returns_winning_index(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_rare", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_rare",
            "amount": 1,
            "request_id": f"win-idx-{uuid.uuid4().hex}",
        },
    )
    data = res.get_json()
    assert data["ok"] is True
    assert isinstance(data.get("winning_index"), int)
    preview = data.get("roll_preview") or []
    assert 0 <= data["winning_index"] < len(preview)


def test_winning_index_points_to_real_reward(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_basic",
            "amount": 1,
            "request_id": f"win-reward-{uuid.uuid4().hex}",
        },
    )
    data = res.get_json()
    assert data["ok"] is True
    rewards = data.get("rewards") or []
    winning = data.get("winning_reward") or {}
    idx = int(data.get("winning_index") or 0)
    preview = data.get("roll_preview") or []
    assert preview
    _preview_matches_winning(preview[idx], winning)
    reward_keys = {str(r["reward_key"]) for r in rewards}
    assert winning["key"] in reward_keys


def test_roll_preview_contains_exact_winning_amount(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_rare", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_rare",
            "amount": 1,
            "request_id": f"win-amt-{uuid.uuid4().hex}",
        },
    )
    data = res.get_json()
    assert data["ok"] is True
    idx = int(data["winning_index"])
    winning = data["winning_reward"]
    tile = (data["roll_preview"] or [])[idx]
    assert int(tile["amount"]) == int(winning["amount"])
    matching = [
        r for r in (data.get("rewards") or [])
        if str(r["reward_key"]) == str(winning["key"])
    ]
    assert matching
    assert int(tile["amount"]) == int(matching[0]["amount"])


def test_multiple_rewards_keep_primary_winning_reward(inventory_db, monkeypatch):
    from game import inventory

    rolls = iter(
        [
            {"reward_type": "resource", "reward_key": "metal", "amount": 5000},
            {"reward_type": "item", "reward_key": "booster_build_15m", "amount": 1},
        ]
    )

    def _fake_roll(pool, rng):
        return dict(next(rolls))

    monkeypatch.setattr(inventory, "_roll_single_reward", _fake_roll)

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_rare", 2, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, _, result = open_containers(uid, pid, "container_rare", 2, conn=conn, rng=random.Random(77))
    assert ok
    commit(conn)

    rewards = (result or {}).get("rewards") or []
    assert len(rewards) >= 2
    winning = (result or {}).get("winning_reward") or {}
    reward_keys = {str(r["reward_key"]) for r in rewards}
    assert winning["key"] in reward_keys
    idx = int((result or {}).get("winning_index") or 0)
    _preview_matches_winning((result or {}).get("roll_preview")[idx], winning)
    conn.close()


def test_roll_preview_contains_real_reward(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_basic",
            "amount": 1,
            "request_id": f"roll-real-{uuid.uuid4().hex}",
        },
    )
    data = res.get_json()
    assert data["ok"] is True
    rewards = data.get("rewards") or []
    assert rewards
    winning = data.get("winning_reward") or {}
    idx = int(data.get("winning_index") or 0)
    preview = data.get("roll_preview") or []
    _preview_matches_winning(preview[idx], winning)
    assert winning["key"] in {str(r["reward_key"]) for r in rewards}


def test_open_container_response_still_has_state_and_inventory(inventory_db, monkeypatch):
    client, uid, _ = _login_client(inventory_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "container_rare", 1, conn=conn)
    conn.commit()
    conn.close()

    res = client.post(
        "/api/inventory/open-container",
        json={
            "item_key": "container_rare",
            "amount": 1,
            "request_id": f"roll-state-{uuid.uuid4().hex}",
        },
    )
    data = res.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert "inventory" in data
    assert isinstance(data["inventory"], dict)
    assert "containers" in data["inventory"]


def test_roll_preview_does_not_change_reward_outcome(inventory_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "container_basic", 2, conn=conn)
    conn.commit()

    rng_a = random.Random(4242)
    begin_write_transaction(conn)
    ok_a, _, result_a = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=rng_a)
    assert ok_a
    commit(conn)

    rng_b = random.Random(4242)
    begin_write_transaction(conn)
    ok_b, _, result_b = open_containers(uid, pid, "container_basic", 1, conn=conn, rng=rng_b)
    assert ok_b
    commit(conn)

    assert (result_a or {}).get("rewards") == (result_b or {}).get("rewards")
    for result in (result_a, result_b):
        preview = (result or {}).get("roll_preview") or []
        assert len(preview) >= 30
        idx = int((result or {}).get("winning_index") or 0)
        winning = (result or {}).get("winning_reward") or {}
        _preview_matches_winning(preview[idx], winning)
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
