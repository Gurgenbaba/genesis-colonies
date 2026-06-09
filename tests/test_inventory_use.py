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
from game.inventory_use import craft_inventory_item, exchange_inventory_item, use_inventory_item
from game.inventory_catalog import (
    all_usable_catalog_keys,
    resolve_item_use_role,
)
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
    """Legacy alias — first job with 2h remaining, 15m booster."""
    test_build_booster_applies_to_queued_build_job(inventory_use_db)


def test_build_booster_applies_to_queued_build_job(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 10, now + 7200, conn=conn)
    grant_inventory_item(uid, "booster_build_1h", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_time"]
    )

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "booster_build_1h", 1, conn=conn)
    assert ok, reason
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
            (pid,),
        ).fetchone()["finish_time"]
    )
    assert finish_after <= finish_before - 3500
    assert int((result or {}).get("effect", {}).get("seconds_reduced") or 0) == 3600
    conn.close()


def test_build_booster_applies_to_waiting_second_job(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 10, now + 3600, conn=conn)
    add_build_job(pid, "crystal_mine", now + 3600, now + 7200, conn=conn)
    grant_inventory_item(uid, "booster_build_1h", 1, conn=conn)
    conn.commit()

    second_before = float(
        conn.execute(
            """
            SELECT finish_time FROM build_queue
            WHERE planet_id = ? ORDER BY finish_time DESC LIMIT 1;
            """,
            (pid,),
        ).fetchone()["finish_time"]
    )

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_build_1h", 1, conn=conn)
    assert ok, reason
    commit(conn)

    last_row = conn.execute(
        """
        SELECT finish_time FROM build_queue
        WHERE planet_id = ? ORDER BY finish_time DESC LIMIT 1;
        """,
        (pid,),
    ).fetchone()
    assert last_row is not None
    second_after = float(last_row["finish_time"])
    assert second_after <= second_before - 3500
    conn.close()


def test_build_booster_consumed_even_if_remaining_time_shorter(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 10, now + 2400, conn=conn)
    grant_inventory_item(uid, "booster_build_1h", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "booster_build_1h", 1, conn=conn)
    assert ok, reason
    commit(conn)

    booster_row = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "booster_build_1h"),
    ).fetchone()
    assert booster_row is None
    assert int((result or {}).get("effect", {}).get("seconds_reduced") or 0) == 3600
    queue_count = conn.execute(
        "SELECT COUNT(*) AS c FROM build_queue WHERE planet_id = ?;",
        (pid,),
    ).fetchone()["c"]
    assert int(queue_count) == 0
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
    assert reason == "no_build_queue"

    amt = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "booster_build_5m"),
    ).fetchone()
    assert int(amt["amount"]) == 1
    conn.close()


def test_use_item_api_does_not_hang_on_build_booster_error(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "booster_build_1h", 1, conn=conn)
    conn.commit()
    conn.close()

    r = client.post(
        "/api/inventory/use-item",
        json={"item_key": "booster_build_1h", "amount": 1},
    )
    assert r.status_code == 400
    payload = r.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "no_build_queue"
    assert "state" in payload


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
    ok, reason, result = use_inventory_item(uid, pid, "booster_research_15m", 1, conn=conn)
    assert ok, reason
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after <= finish_before - 800
    assert int((result or {}).get("effect", {}).get("seconds_reduced") or 0) == 900
    conn.close()


def test_research_booster_applies_to_waiting_second_job(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_research_job(uid, "energy_tech", now - 10, now + 3600, conn=conn)
    add_research_job(uid, "mining_tech", now + 3600, now + 7200, conn=conn)
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    conn.commit()

    second_before = float(
        conn.execute(
            """
            SELECT finish_at FROM research_queue
            WHERE user_id = ? ORDER BY finish_at DESC LIMIT 1;
            """,
            (uid,),
        ).fetchone()["finish_at"]
    )

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_research_15m", 1, conn=conn)
    assert ok, reason
    commit(conn)

    second_after = float(
        conn.execute(
            """
            SELECT finish_at FROM research_queue
            WHERE user_id = ? ORDER BY finish_at DESC LIMIT 1;
            """,
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert second_after <= second_before - 800
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
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    grant_inventory_item(uid, "fragment_dna_common", 17, conn=conn)
    grant_inventory_item(uid, "mythic_genesis_core", 1, conn=conn)
    conn.commit()

    state = build_inventory_state(uid, conn=conn)
    assert inventory_schema_ready(conn)
    by_key = {i["item_key"]: i for i in state["other_items"]}
    assert by_key["booster_build_5m"]["usable"] is False
    assert by_key["booster_build_5m"]["use_block_reason"] == "no_build_queue"
    assert by_key["booster_research_15m"]["usable"] is False
    assert by_key["booster_research_15m"]["use_block_reason"] == "no_research_queue"
    assert by_key["fragment_dna_common"]["craft_material"] is True
    assert by_key["fragment_dna_common"]["craft_progress"][0]["owned"] == 17
    assert by_key["mythic_genesis_core"]["collectible"] is True
    assert by_key["mythic_genesis_core"]["usable"] is False
    conn.close()


def test_time_booster_usable_when_queue_active(inventory_use_db):
    from game.inventory import build_inventory_state

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)
    add_research_job(uid, "energy_tech", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_build_5m", 1, conn=conn)
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    conn.commit()

    state = build_inventory_state(uid, conn=conn)
    by_key = {i["item_key"]: i for i in state["other_items"]}
    assert by_key["booster_build_5m"]["usable"] is True
    assert by_key["booster_research_15m"]["usable"] is True
    conn.close()


def test_research_booster_not_consumed_without_job(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_research_15m", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "no_research_queue"

    amt = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "booster_research_15m"),
    ).fetchone()
    assert int(amt["amount"]) == 1
    conn.close()


def test_shipyard_booster_not_consumed_without_job(inventory_use_db):
    from game.shipyard_queue import shipyard_queue_table_ready

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    if not shipyard_queue_table_ready(conn):
        pytest.skip("shipyard_queue schema not ready")
    grant_inventory_item(uid, "booster_shipyard_15m", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "booster_shipyard_15m", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "no_shipyard_queue"
    conn.close()


def test_all_usable_catalog_items_have_effect_handler(inventory_use_db):
    from game.inventory_use import _resolve_use_spec

    for key in all_usable_catalog_keys():
        kind, effect = _resolve_use_spec(key)
        assert kind, f"{key} has no use handler kind"
        assert kind not in ("collectible", "craft_material", "exchange_material"), key
        if kind == "research_datacore":
            assert effect.get("tech_keys"), key
            assert int(effect.get("seconds") or 0) > 0, key
        elif kind == "time_boost":
            assert int(effect.get("seconds") or 0) > 0, key


def test_collectibles_do_not_render_as_usable(inventory_use_db):
    from game.inventory import build_inventory_state
    from game.inventory_catalog import COLLECTIBLE_ITEM_KEYS

    conn = db()
    uid = _player(conn=conn)
    for key in list(COLLECTIBLE_ITEM_KEYS)[:3]:
        grant_inventory_item(uid, key, 1, conn=conn)
    conn.commit()

    state = build_inventory_state(uid, conn=conn)
    by_key = {i["item_key"]: i for i in state["other_items"]}
    for key in list(COLLECTIBLE_ITEM_KEYS)[:3]:
        row = by_key[key]
        assert row["collectible"] is True
        assert row["usable"] is False
        assert resolve_item_use_role(key) == "collectible"
    conn.close()


def test_datacore_mining_reduces_matching_research_queue(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_research_job(uid, "mining_tech", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "research_data_mining", 1, conn=conn)
    conn.commit()

    finish_before = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "research_data_mining", 1, conn=conn)
    assert ok, reason
    commit(conn)

    finish_after = float(
        conn.execute(
            "SELECT finish_at FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC LIMIT 1;",
            (uid,),
        ).fetchone()["finish_at"]
    )
    assert finish_after <= finish_before - 800
    row = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "research_data_mining"),
    ).fetchone()
    assert row is None
    assert int((result or {}).get("effect", {}).get("seconds_reduced") or 0) == 900
    conn.close()


def test_datacore_without_matching_research_not_consumed(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "research_data_mining", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "research_data_mining", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "no_matching_research"

    amt = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "research_data_mining"),
    ).fetchone()
    assert int(amt["amount"]) == 1
    conn.close()


def test_dna_core_common_to_rare_exchange(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = exchange_inventory_item(uid, "dna_core_common_to_rare", 1, conn=conn)
    assert ok, reason
    commit(conn)

    common = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_common"),
    ).fetchone()
    assert common is None
    rare = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_rare"),
    ).fetchone()
    assert int(rare["amount"]) == 1
    assert (result or {}).get("exchange", {}).get("output_key") == "dna_core_rare"
    conn.close()


def test_dna_core_rare_to_epic_exchange(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    grant_inventory_item(uid, "dna_core_rare", 5, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = exchange_inventory_item(uid, "dna_core_rare_to_epic", 1, conn=conn)
    assert ok, reason
    commit(conn)

    rare = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_rare"),
    ).fetchone()
    assert rare is None
    epic = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_epic"),
    ).fetchone()
    assert int(epic["amount"]) == 1
    assert (result or {}).get("exchange", {}).get("output_key") == "dna_core_epic"
    conn.close()


def test_dna_exchange_insufficient_material(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    grant_inventory_item(uid, "dna_core_common", 3, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = exchange_inventory_item(uid, "dna_core_common_to_rare", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "insufficient_materials"

    amt = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_common"),
    ).fetchone()
    assert int(amt["amount"]) == 3
    conn.close()


def test_inventory_exchange_idempotency(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()
    conn.close()

    req_id = f"test-exchange-{uuid.uuid4().hex}"
    body = {"recipe_key": "dna_core_common_to_rare", "amount": 1, "request_id": req_id}
    r1 = client.post("/api/inventory/exchange", json=body)
    r2 = client.post("/api/inventory/exchange", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.get_json()["ok"] is True
    assert r2.get_json() == r1.get_json()

    conn = db()
    rare = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "dna_core_rare"),
    ).fetchone()
    assert int(rare["amount"]) == 1
    conn.close()


def test_inventory_actions_return_json_on_error(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "research_data_mining", 1, conn=conn)
    conn.commit()
    conn.close()

    r = client.post(
        "/api/inventory/use-item",
        json={"item_key": "research_data_mining", "amount": 1},
    )
    assert r.status_code == 400
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload["ok"] is False
    assert payload["reason"] == "no_matching_research"
    assert payload.get("message")
    assert "state" in payload
    assert "inventory" in payload

    r2 = client.post(
        "/api/inventory/exchange",
        json={"recipe_key": "dna_core_common_to_rare", "amount": 1},
    )
    assert r2.status_code == 400
    assert r2.content_type.startswith("application/json")
    payload2 = r2.get_json()
    assert payload2["ok"] is False
    assert payload2["reason"] == "insufficient_materials"


def test_dna_cores_not_usable(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "dna_core_common", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "item_not_usable"
    conn.close()


def _assert_inventory_json_response(response, *, expect_ok: bool):
    assert response.content_type.startswith("application/json")
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert payload.get("ok") is expect_ok
    assert "state" in payload
    assert "inventory" in payload
    if not expect_ok:
        assert payload.get("message")
        assert payload.get("reason")
    return payload


def test_all_inventory_use_actions_return_json(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)
    add_research_job(uid, "mining_tech", now - 5, now + 3600, conn=conn)
    grant_inventory_item(uid, "booster_build_5m", 1, conn=conn)
    grant_inventory_item(uid, "booster_research_15m", 1, conn=conn)
    grant_inventory_item(uid, "research_data_mining", 1, conn=conn)
    grant_inventory_item(uid, "resource_pack_ferronit", 1, conn=conn)
    grant_inventory_item(uid, "evo_planet_xp_500", 1, conn=conn)
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    grant_inventory_item(uid, "container_basic", 1, conn=conn)
    conn.commit()
    conn.close()

    cases = [
        ("/api/inventory/use-item", {"item_key": "resource_pack_ferronit", "amount": 1}, True),
        ("/api/inventory/use-item", {"item_key": "booster_build_5m", "amount": 1}, True),
        ("/api/inventory/use-item", {"item_key": "booster_research_15m", "amount": 1}, True),
        ("/api/inventory/use-item", {"item_key": "research_data_mining", "amount": 1}, True),
        ("/api/inventory/use-item", {"item_key": "evo_planet_xp_500", "amount": 1}, True),
        ("/api/inventory/craft", {"recipe_key": "dna_core_common", "amount": 1}, True),
        ("/api/inventory/exchange", {"recipe_key": "dna_core_common_to_rare", "amount": 1}, True),
        ("/api/inventory/open-container", {"item_key": "container_basic", "amount": 1}, True),
        ("/api/inventory/use-item", {"item_key": "not_a_real_item", "amount": 1}, False),
    ]
    for url, body, expect_ok in cases:
        r = client.post(url, json=body)
        _assert_inventory_json_response(r, expect_ok=expect_ok)


def test_mutation_results_do_not_include_inventory(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "resource_pack_ferronit", 1, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = use_inventory_item(uid, pid, "resource_pack_ferronit", 1, conn=conn)
    assert ok, reason
    rollback(conn)
    assert "inventory" not in (result or {})

    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, result = craft_inventory_item(uid, "dna_core_common", 1, conn=conn)
    rollback(conn)
    if ok:
        assert "inventory" not in (result or {})

    begin_write_transaction(conn)
    ok, reason, result = exchange_inventory_item(uid, "dna_core_common_to_rare", 1, conn=conn)
    assert ok, reason
    rollback(conn)
    assert "inventory" not in (result or {})
    conn.close()


def test_inventory_state_built_after_commit(inventory_use_db, monkeypatch):
    from game import inventory as inv_mod

    build_calls = []

    original_build = inv_mod.build_inventory_state

    def tracked_build(user_id, *, conn):
        build_calls.append(user_id)
        return original_build(user_id, conn=conn)

    monkeypatch.setattr(inv_mod, "build_inventory_state", tracked_build)

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "resource_pack_crytite", 1, conn=conn)
    conn.commit()
    conn.close()

    build_calls.clear()
    ok, reason, result = inv_mod.run_inventory_mutation(
        lambda c: use_inventory_item(uid, pid, "resource_pack_crytite", 1, conn=c)
    )
    assert ok, reason
    assert "inventory" not in (result or {})
    assert len(build_calls) == 0

    client, _, _ = _login_client(inventory_use_db, monkeypatch)
    build_calls.clear()
    r = client.post("/api/inventory/use-item", json={"item_key": "resource_pack_crytite", "amount": 1})
    assert r.status_code == 400
    payload = r.get_json()
    assert payload["ok"] is False
    assert len(build_calls) >= 1


@pytest.mark.parametrize(
    "item_key,setup_fn",
    [
        ("booster_build_5m", lambda uid, pid, conn, now: add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)),
        ("booster_research_15m", lambda uid, pid, conn, now: add_research_job(uid, "energy_tech", now - 5, now + 3600, conn=conn)),
        ("research_data_mining", lambda uid, pid, conn, now: add_research_job(uid, "mining_tech", now - 5, now + 3600, conn=conn)),
        ("resource_pack_ferronit", lambda uid, pid, conn, now: None),
        ("evo_planet_xp_500", lambda uid, pid, conn, now: None),
    ],
)
def test_inventory_use_actions_no_lock(inventory_use_db, monkeypatch, item_key, setup_fn):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    setup_fn(uid, pid, conn, now)
    grant_inventory_item(uid, item_key, 1, conn=conn)
    conn.commit()
    conn.close()

    r = client.post("/api/inventory/use-item", json={"item_key": item_key, "amount": 1})
    payload = _assert_inventory_json_response(r, expect_ok=True)
    assert payload.get("item_key") == item_key or payload.get("consumed", 0) >= 1


def test_craft_no_lock(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "fragment_dna_common", 50, conn=conn)
    conn.commit()
    conn.close()

    r = client.post("/api/inventory/craft", json={"recipe_key": "dna_core_common", "amount": 1})
    _assert_inventory_json_response(r, expect_ok=True)


def test_exchange_no_lock(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()
    conn.close()

    r = client.post("/api/inventory/exchange", json={"recipe_key": "dna_core_common_to_rare", "amount": 1})
    _assert_inventory_json_response(r, expect_ok=True)


def test_shipyard_booster_no_lock(inventory_use_db, monkeypatch):
    from game.shipyard_queue import shipyard_queue_table_ready

    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    if not shipyard_queue_table_ready(conn):
        pytest.skip("shipyard_queue schema not ready")
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
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
    conn.close()

    r = client.post("/api/inventory/use-item", json={"item_key": "booster_shipyard_15m", "amount": 1})
    _assert_inventory_json_response(r, expect_ok=True)


def test_dna_cores_not_usable(inventory_use_db):
    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    grant_inventory_item(uid, "dna_core_common", 5, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    ok, reason, _ = use_inventory_item(uid, pid, "dna_core_common", 1, conn=conn)
    rollback(conn)
    assert not ok
    assert reason == "item_not_usable"
    conn.close()


def test_build_booster_short_remaining_no_db_lock(inventory_use_db, monkeypatch):
    client, uid, _ = _login_client(inventory_use_db, monkeypatch)
    conn = db()
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 10, now + 14 * 60, conn=conn)
    grant_inventory_item(uid, "booster_build_1h", 1, conn=conn)
    conn.commit()
    conn.close()

    r = client.post("/api/inventory/use-item", json={"item_key": "booster_build_1h", "amount": 1})
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["ok"] is True
    assert payload.get("consumed") == 1

    conn = db()
    queue_count = conn.execute(
        "SELECT COUNT(*) AS c FROM build_queue WHERE planet_id = ?;",
        (pid,),
    ).fetchone()["c"]
    booster_row = conn.execute(
        "SELECT amount FROM player_inventory_items WHERE user_id = ? AND item_key = ?;",
        (uid, "booster_build_1h"),
    ).fetchone()
    conn.close()
    assert int(queue_count) == 0
    assert booster_row is None


def test_finish_due_work_once_nested_no_begin_immediate(inventory_use_db, monkeypatch):
    from game import db as dbmod
    from game.queue_engine import finish_due_work_once

    begin_calls = []

    def spy_begin(conn, **kwargs):
        begin_calls.append(1)
        return dbmod.begin_write_transaction(conn, **kwargs)

    monkeypatch.setattr(dbmod, "begin_write_transaction", spy_begin)

    conn = db()
    uid = _player(conn=conn)
    planet = get_context_planet(uid, conn=conn)
    pid = int(planet["id"])
    now = time.time()
    add_build_job(pid, "metal_mine", now - 5, now + 3600, conn=conn)
    conn.commit()

    begin_write_transaction(conn)
    begin_calls.clear()
    finish_due_work_once(uid, pid, conn=conn, dedup=False, manage_transaction=False)
    assert len(begin_calls) == 0
    rollback(conn)
    conn.close()
