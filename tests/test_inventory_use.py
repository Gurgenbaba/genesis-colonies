"""GC-541 — Inventory item use & craft."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game import db as gdb
from game.db import begin_write_transaction, commit, db, rollback
from game.inventory import grant_inventory_item, inventory_schema_ready
from game.inventory_use import craft_inventory_item, use_inventory_item
from game.models import (
    add_build_job,
    add_research_job,
    create_user,
    ensure_player_and_homeworld,
    get_idempotent_action,
    get_planets_by_player,
    init_db,
    save_idempotent_action,
)
from game.planet_evolution.repository import get_context_planet


@pytest.fixture
def inventory_use_db(tmp_path, monkeypatch):
    db_path = tmp_path / "inventory_use.db"
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
    ok, err, user = create_user(f"invuse_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="UseTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _login_client(inventory_use_db, monkeypatch):
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
        "SELECT metal, crystal, fuel_cells, planet_xp FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    return (
        float(row["metal"]),
        float(row["crystal"]),
        float(row["fuel_cells"] or 0),
        int(row["planet_xp"] or 0),
    )


def test_resource_pack_credits_and_consumes(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "resource_pack_ferronit", 2, conn=conn)
    metal_before, _, _, _ = _planet_resources(conn, pid)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "resource_pack_ferronit", 1, conn=conn)
    assert ok, reason
    commit(conn)

    metal_after, _, _, _ = _planet_resources(conn, pid)
    assert metal_after >= metal_before + 50_000
    row = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "resource_pack_ferronit"),
    ).fetchone()
    assert row is None or int(row["amount"]) == 1
    assert (result or {}).get("consumed") == 1
    conn.close()


def test_build_booster_reduces_queue_time(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 10, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_build_15m", 1, conn=conn)
    conn.commit()

    row_before = conn.execute(
        "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
        (pid,),
    ).fetchone()
    finish_before = float(row_before["finish_time"])

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "booster_build_15m", 1, conn=conn)
    assert ok, reason
    commit(conn)

    row_after = conn.execute(
        "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
        (pid,),
    ).fetchone()
    finish_after = float(row_after["finish_time"])
    assert finish_after <= finish_before - 800
    assert int((result or {}).get("effect", {}).get("seconds_reduced") or 0) >= 800
    conn.close()


def test_build_booster_not_consumed_without_job(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "booster_build_5m", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_build_5m", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "no_effect_target"

    amt = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "booster_build_5m"),
    ).fetchone()
    assert int(amt["amount"]) == 1
    conn.close()


def test_research_booster_reduces_research_time(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_research_job(uid, "energy_tech", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_research_15m", 1, conn=conn)
    assert ok, reason
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after <= finish_before - 800
    conn.close()


def test_shipyard_booster_reduces_shipyard_time(inventory_use_db):
    from game.shipyard_queue import shipyard_queue_table_ready

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    if not shipyard_queue_table_ready(conn):
        pytest.skip("shipyard_queue schema not ready")
    now = time.time()
    conn.execute(
        """
        INSERT INTO shipyard_queue (
            player_id, planet_id, ship_key, amount, status,
            started_at, finish_at, created_at, queue_position,
            cost_metal, cost_crystal, cost_fuel_cells
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (uid, pid, "spark_drone", 1, "queued", now - 5, now + 1800, now, 0, 0, 0, 0),
    )
    grant_inventory_item(uid, "booster_shipyard_15m", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_at FROM shipyard_queue WHERE planet_id = ? ORDER BY queue_position ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_at"]
    )

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_shipyard_15m", 1, conn=conn)
    assert ok, reason
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM shipyard_queue WHERE planet_id = ? ORDER BY queue_position ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after <= finish_before - 800
    conn.close()


def test_planet_xp_item_increases_xp(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    _, _, _, xp_before = _planet_resources(conn, pid)
    grant_inventory_item(uid, "evo_planet_xp_5000", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "evo_planet_xp_5000", 1, conn=conn)
    assert ok, reason
    commit(conn)

    _, _, _, xp_after = _planet_resources(conn, pid)
    assert xp_after >= xp_before + 5000
    assert int((result or {}).get("effect", {}).get("xp_gained") or 0) >= 5000
    conn.close()


def test_fragment_crafting_consumes_and_creates_core(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = craft_inventory_item(uid, "dna_core_common", 1, conn=conn)
    assert ok, reason
    commit(conn)

    common = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "fragment_dna_common"),
    ).fetchone()
    assert common is None
    core = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_common"),
    ).fetchone()
    assert int(core["amount"]) == 1
    assert (result or {}).get("output_key") == "dna_core_common"
    conn.close()


def test_use_item_idempotency_via_api(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "resource_pack_crytite", 1, conn=conn)
    conn.commit()
    conn.close()

    req_id = f"test-idem-{uuid.uuid4().hex}"
    body = {"item_key": "resource_pack_crytite", "amount": 1, "request_id": req_id}
    r1 = client.post("/api/inventory/use-item", json=body)
    r2 = client.post("/api/inventory/use-item", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json()["ok"] is True
    assert r2.get_json() == r1.get_json()

    conn = db()
    row = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "resource_pack_crytite"),
    ).fetchone()
    assert row is None
    conn.close()


def test_invalid_item_rejected(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "not_a_real_item", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "invalid_item"
    conn.close()


def test_collectible_not_usable(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "mythic_genesis_core", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "mythic_genesis_core", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "item_not_usable"
    conn.close()


def test_inventory_state_includes_use_metadata(inventory_use_db):
    from game.inventory import build_inventory_state

    conn = db()
    uid = _player(conn=conn)
    grant_inventory_item(uid, "booster_build_5m", 1, conn=conn)
    grant_inventory_item(uid, "fragment_dna_common", 17, conn=conn)
    grant_inventory_item(uid, "mythic_genesis_core", 1, conn=conn)
    conn.commit()

    state = build_inventory_state(uid, conn=conn)
    assert inventory_schema_ready(conn)
    by_key = {i["item_key"]: i for i in state["other_items"]}
    assert by_key["booster_build_5m"]["usable"] is True
    assert by_key["fragment_dna_common"]["craft_material"] is True
    assert by_key["fragment_dna_common"]["craft_progress"][0]["owned"] == 17
    assert by_key["mythic_genesis_core"]["collectible"] is True
    assert by_key["mythic_genesis_core"]["usable"] is False
    conn.close()
