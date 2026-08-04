"""Secret Vault Raid — ground phase + troop train + steal cap contracts (GC-VAULT)."""
from __future__ import annotations

import random
import time
import uuid
from unittest.mock import patch

import pytest

from game import db as gdb
from game.db import db, rollback
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_homeworld,
    get_planet_buildings,
    init_db,
    save_planet_buildings,
)
from game.troop_defs import barracks_troop_capacity
from game.troops import enqueue_troop_train, finish_planet_troop_jobs, get_planet_troops
from game.combat import simulate_ground_raid
from game.vault_raid import (
    VAULT_BOX_CAP,
    VAULT_TK_CAP_SEC,
    apply_vault_steal,
    vault_snapshot,
)


def test_ground_raid_fail_survivors_and_caps():
    rng = random.Random(7)
    ground = simulate_ground_raid(
        {"militia": 40},
        {"vault_guard": 80},
        barracks_level=8,
        rng=rng,
    )
    assert ground["winner"] == "defender"
    assert sum((ground.get("attacker_survivors") or {}).values()) <= 8
    assert VAULT_TK_CAP_SEC == 21600
    assert VAULT_BOX_CAP == 5


def test_ground_raid_win_reduces_defenders():
    rng = random.Random(1)
    ground = simulate_ground_raid(
        {"breach_team": 30, "militia": 20},
        {"militia": 5},
        barracks_level=1,
        rng=rng,
    )
    assert ground["winner"] == "attacker"
    assert sum((ground.get("defender_survivors") or {}).values()) <= 1


def test_held_raid_reason_contract():
    ground = simulate_ground_raid(
        {"militia": 5},
        {"vault_guard": 100},
        barracks_level=10,
        rng=random.Random(99),
    )
    assert ground["winner"] == "defender"
    assert ground.get("reason") == "vault_held"


def test_vault_snapshot_caps_with_mocks():
    with patch("game.vault_raid.get_balance", create=True), patch(
        "game.timekeeper.get_balance", return_value=50_000
    ), patch(
        "game.vault_raid.list_vault_boxes",
        return_value=[{"item_key": f"container_rare", "rarity": "uncommon"} for _ in range(5)],
    ), patch("game.vault_raid.table_ready_inventory", return_value=True):
        snap = vault_snapshot(1, conn=object())
    assert snap["timekeeper_sec"] == VAULT_TK_CAP_SEC
    assert snap["box_count"] == VAULT_BOX_CAP


def test_apply_vault_steal_empty_same_player():
    out = apply_vault_steal(attacker_id=1, defender_id=1, conn=object())
    assert out["empty_vault"] is True
    assert out["timekeeper_stolen"] == 0


@pytest.fixture
def vault_conn(tmp_path, monkeypatch):
    db_path = tmp_path / "vault_raid.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    conn = db()
    try:
        yield conn
    finally:
        try:
            rollback(conn)
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        gdb._DB_PATH = None


def test_troop_train_and_finish(vault_conn):
    conn = vault_conn
    ok, err, user = create_user(f"tr_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Train", conn=conn)
    planet_id = int(get_homeworld(player_id=uid, conn=conn)["id"])
    bld = get_planet_buildings(planet_id, conn=conn)
    bld["barracks"] = 5
    save_planet_buildings(planet_id, bld, conn=conn)
    conn.execute(
        "UPDATE planets SET metal = metal + 50000, crystal = crystal + 50000 WHERE id = ?;",
        (planet_id,),
    )
    conn.commit()
    ok, reason, result = enqueue_troop_train(
        player_id=uid,
        planet_id=planet_id,
        troop_key="militia",
        amount=2,
        conn=conn,
    )
    assert ok, reason
    assert result and result["amount"] == 2
    finished = finish_planet_troop_jobs(planet_id, conn=conn, now=time.time() + 10_000)
    assert finished >= 1
    assert int(get_planet_troops(planet_id, conn=conn).get("militia") or 0) >= 2
    assert barracks_troop_capacity(5) == 20 + 5 * 200 + (5 ** 4) * 16
    conn.commit()


def test_barracks_troop_capacity_breakpoints():
    assert barracks_troop_capacity(0) == 0
    assert barracks_troop_capacity(1) == 236
    assert barracks_troop_capacity(10) == 162020
    assert barracks_troop_capacity(25) == 6_255_020
    assert barracks_troop_capacity(50) == 100_010_020


def test_troop_train_uses_production_cycles():
    from game.shipyard import orbital_production_batch_capacity, production_job_duration_seconds
    from game.troops import barracks_batch_capacity, unit_train_seconds, _job_duration_seconds

    assert barracks_batch_capacity(5) == orbital_production_batch_capacity(5)
    unit = unit_train_seconds("militia", 5)
    assert unit == unit_train_seconds("militia", 5)
    assert unit < unit_train_seconds("militia", 1) or unit == unit_train_seconds("militia", 1)
    # Large order: fewer wall-clock seconds than linear amount × cycle
    linear = unit * 1000
    batched = _job_duration_seconds("militia", 1000, 5)
    assert batched == production_job_duration_seconds(
        unit_seconds=unit,
        amount=1000,
        batch_capacity=barracks_batch_capacity(5),
    )
    assert batched < linear
    assert batched >= unit
