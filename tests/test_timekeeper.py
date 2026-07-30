"""
GC-TIMEKEEPER-001 — Imperium time account contracts.

Run: python -m pytest tests/test_timekeeper.py tests/test_inventory_use.py -v -k timekeeper or booster
"""

from __future__ import annotations

import time
import uuid

import pytest

from game.db import begin_write_transaction, commit, db, rollback
from game.inventory import grant_inventory_item
from game.inventory_use import deposit_timekeeper_domain, use_inventory_item
from game.models import add_build_job, create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet
from game.timekeeper import (
    apply_timekeeper,
    credit,
    credit_from_booster_item,
    debit,
    deposit_legacy_domain,
    get_balance,
    schema_ready,
    serialize_for_client,
)


@pytest.fixture
def timekeeper_db(tmp_path, monkeypatch):
    db_path = tmp_path / "timekeeper.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb

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
    ok, err, user = create_user(f"tk_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="TkTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_timekeeper_schema_ready(timekeeper_db):
    conn = db()
    try:
        assert schema_ready(conn) is True
    finally:
        conn.close()


def test_timekeeper_credit_debit_and_serialize(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        credit(uid, 3600, "test", conn=conn)
        assert get_balance(uid, conn=conn) == 3600
        debit(uid, 900, "apply:test", conn=conn)
        assert get_balance(uid, conn=conn) == 2700
        commit(conn)
        payload = serialize_for_client(uid, conn=conn)
        assert payload["balance_sec"] == 2700
        assert "45min" in payload["label"] or "2700" in payload["label"]
    finally:
        conn.close()


def test_legacy_booster_credits_timekeeper_not_queue(timekeeper_db):
    conn = db()
    try:
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
        assert finish_after == finish_before
        assert get_balance(uid, conn=conn) == 3600
        effect = (result or {}).get("effect") or {}
        assert effect.get("kind") == "timekeeper_credit"
        assert int(effect.get("seconds_credited") or 0) == 3600
    finally:
        conn.close()


def test_deposit_legacy_domain_credits_all_build_boosters(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        grant_inventory_item(uid, "booster_build_15m", 3, conn=conn)
        grant_inventory_item(uid, "booster_build_1h", 2, conn=conn)
        grant_inventory_item(uid, "booster_research_15m", 4, conn=conn)
        conn.commit()

        begin_write_transaction(conn)
        ok, reason, result = deposit_timekeeper_domain(uid, "build", conn=conn)
        assert ok, reason
        commit(conn)

        expected = 3 * 15 * 60 + 2 * 3600
        assert get_balance(uid, conn=conn) == expected
        assert int((result or {}).get("consumed") or 0) == 5
        effect = (result or {}).get("effect") or {}
        assert effect.get("kind") == "timekeeper_credit"
        assert int(effect.get("seconds_credited") or 0) == expected

        from game.inventory import inventory_amount

        assert inventory_amount(uid, "booster_build_15m", conn=conn) == 0
        assert inventory_amount(uid, "booster_build_1h", conn=conn) == 0
        assert inventory_amount(uid, "booster_research_15m", conn=conn) == 4
    finally:
        conn.close()


def test_deposit_legacy_domain_helper_rejects_empty(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        ok, reason, _ = deposit_legacy_domain(uid, "build", conn=conn)
        rollback(conn)
        assert ok is False
        assert reason == "no_depositable_items"
    finally:
        conn.close()


def test_deposit_legacy_domain_all_credits_every_domain(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        grant_inventory_item(uid, "booster_build_15m", 2, conn=conn)
        grant_inventory_item(uid, "booster_research_1h", 1, conn=conn)
        grant_inventory_item(uid, "booster_shipyard_15m", 3, conn=conn)
        conn.commit()

        begin_write_transaction(conn)
        ok, reason, result = deposit_timekeeper_domain(uid, "all", conn=conn)
        assert ok, reason
        commit(conn)

        expected = 2 * 15 * 60 + 1 * 3600 + 3 * 15 * 60
        assert get_balance(uid, conn=conn) == expected
        assert int((result or {}).get("consumed") or 0) == 6
        effect = (result or {}).get("effect") or {}
        assert effect.get("kind") == "timekeeper_credit"
        assert effect.get("domain") == "all"
        assert int(effect.get("seconds_credited") or 0) == expected
        assert (result or {}).get("item_key") == "timekeeper_deposit:all"

        from game.inventory import inventory_amount

        assert inventory_amount(uid, "booster_build_15m", conn=conn) == 0
        assert inventory_amount(uid, "booster_research_1h", conn=conn) == 0
        assert inventory_amount(uid, "booster_shipyard_15m", conn=conn) == 0
    finally:
        conn.close()


def test_timekeeper_apply_build_reduces_queue(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 7200, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 3600, "test", conn=conn)
        commit(conn)

        finish_before = float(
            conn.execute(
                "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
                (pid,),
            ).fetchone()["finish_time"]
        )

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(
            uid,
            "build",
            planet_id=pid,
            seconds=1800,
            mode="partial",
            conn=conn,
        )
        assert ok, reason
        commit(conn)

        finish_after = float(
            conn.execute(
                "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
                (pid,),
            ).fetchone()["finish_time"]
        )
        assert finish_after <= finish_before - 1700
        assert get_balance(uid, conn=conn) == 1800
        assert int(result.get("seconds_applied") or 0) >= 1700
    finally:
        conn.close()


def test_credit_from_booster_item_helper(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        effect = credit_from_booster_item(uid, "booster_research_30m", conn=conn)
        commit(conn)
        assert effect is not None
        assert int(effect.get("seconds_credited") or 0) == 1800
        assert get_balance(uid, conn=conn) == 1800
    finally:
        conn.close()


def _api_client(timekeeper_db, monkeypatch):
    import importlib
    import os

    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    conn.close()

    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    return client, uid


def test_api_timekeeper_apply_returns_state(timekeeper_db, monkeypatch):
    client, uid = _api_client(timekeeper_db, monkeypatch)
    conn = db()
    try:
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 7200, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 3600, "test", conn=conn)
        commit(conn)
    finally:
        conn.close()

    res = client.post(
        "/api/timekeeper/apply",
        json={"domain": "build", "mode": "partial", "seconds": 1800},
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    assert res.status_code == 200
    payload = res.get_json()
    assert payload["ok"] is True
    assert int(payload.get("seconds_applied") or 0) >= 1700
    state = payload.get("state") or {}
    assert state.get("timekeeper", {}).get("balance_sec") == 1800
    assert payload.get("timekeeper", {}).get("balance_sec") == 1800


def test_timekeeper_finish_clamps_to_remaining(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 8, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 1200, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(uid, "build", planet_id=pid, mode="finish", conn=conn)
        assert ok, reason
        commit(conn)

        assert int(result.get("seconds_applied") or 0) <= 8
        assert get_balance(uid, conn=conn) == 1200 - int(result.get("seconds_applied") or 0)
        row = conn.execute(
            "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
            (pid,),
        ).fetchone()
        assert row is None or float(row["finish_time"]) <= now + 1
    finally:
        conn.close()


def test_timekeeper_partial_clamps_to_remaining(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 8, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 1200, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(
            uid, "build", planet_id=pid, seconds=1800, mode="partial", conn=conn
        )
        assert ok, reason
        commit(conn)

        applied = int(result.get("seconds_applied") or 0)
        assert applied <= 8
        assert get_balance(uid, conn=conn) == 1200 - applied
    finally:
        conn.close()


def test_timekeeper_finish_only_active_head_not_full_queue(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 120, conn=conn)
        add_build_job(pid, "crystal_mine", now + 120, now + 240, conn=conn)
        add_build_job(pid, "solar_plant", now + 240, now + 360, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 3600, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(uid, "build", planet_id=pid, mode="finish", conn=conn)
        assert ok, reason
        commit(conn)

        applied = int(result.get("seconds_applied") or 0)
        assert applied <= 120
        rows = conn.execute(
            "SELECT building_type, finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC;",
            (pid,),
        ).fetchall()
        assert len(rows) == 2
        assert str(rows[-1]["building_type"]) == "solar_plant"
        assert float(rows[-1]["finish_time"]) > now + 60
    finally:
        conn.close()


def test_timekeeper_max_uses_balance_not_full_remaining(timekeeper_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        now = time.time()
        add_build_job(pid, "metal_mine", now - 10, now + 7200, conn=conn)
        begin_write_transaction(conn)
        credit(uid, 1200, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(uid, "build", planet_id=pid, mode="max", conn=conn)
        assert ok, reason
        commit(conn)

        assert int(result.get("seconds_applied") or 0) == 1200
        assert get_balance(uid, conn=conn) == 0
        finish_after = float(
            conn.execute(
                "SELECT finish_time FROM build_queue WHERE planet_id = ? ORDER BY finish_time ASC LIMIT 1;",
                (pid,),
            ).fetchone()["finish_time"]
        )
        assert finish_after <= now + 7200 - 1100
    finally:
        conn.close()


def _grant_shipyard_tk_prereqs(cur, planet_id: int, user_id: int) -> None:
    cur.execute(
        """
        UPDATE planet_buildings
        SET orbital_shipyard = 1, research_lab = 10, command_center = 10, barracks = 10
        WHERE planet_id = ?;
        """,
        (int(planet_id),),
    )
    for tech in (
        "energy_tech",
        "mining_tech",
        "drone_tech",
        "engine_tech",
        "navigation_tech",
        "weapon_tech",
        "armor_tech",
        "storage_tech",
        "fuel_efficiency",
        "shield_tech",
    ):
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(user_id), tech, 10),
        )


def test_timekeeper_shipyard_debit_matches_batch_remaining_not_serial(timekeeper_db):
    """TK cost for shipyard uses batch finish_at, never amount × unit_seconds."""
    from game.shipyard import (
        build_ship,
        orbital_production_batch_capacity,
        production_job_duration_seconds,
        unit_build_seconds,
    )

    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (5_000_000, 5_000_000, 500_000, pid),
        )
        _grant_shipyard_tk_prereqs(cur, pid, uid)
        conn.commit()

        qty = 40
        ok, reason, _ = build_ship(
            player_id=uid, planet_id=pid, ship_key="mule_courier", amount=qty, conn=conn
        )
        assert ok, reason
        unit = unit_build_seconds("mule_courier", 1, conn=conn, planet_id=pid)
        cap = orbital_production_batch_capacity(1)
        batch_remaining = production_job_duration_seconds(
            unit_seconds=unit, amount=qty, batch_capacity=cap
        )
        serial_remaining = qty * unit
        assert batch_remaining < serial_remaining

        begin_write_transaction(conn)
        credit(uid, serial_remaining + 10_000, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(
            uid, "shipyard", planet_id=pid, mode="finish", conn=conn
        )
        assert ok, reason
        commit(conn)

        applied = int(result.get("seconds_applied") or 0)
        assert applied <= batch_remaining + 2
        assert applied < serial_remaining
        assert get_balance(uid, conn=conn) == serial_remaining + 10_000 - applied
    finally:
        conn.close()


def test_timekeeper_defense_debit_matches_batch_remaining_not_serial(timekeeper_db):
    """TK cost for defense uses batch finish_at, never amount × unit_seconds."""
    from game.defense import build_defense, unit_build_seconds
    from game.shipyard import orbital_production_batch_capacity, production_job_duration_seconds

    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (5_000_000, 5_000_000, 500_000, pid),
        )
        cur.execute(
            "UPDATE planet_buildings SET defense_factory = 1, orbital_shipyard = 1 WHERE planet_id = ?;",
            (pid,),
        )
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, 'weapon_tech', 2)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (uid,),
        )
        conn.commit()

        qty = 20
        ok, reason, _ = build_defense(
            player_id=uid,
            planet_id=pid,
            defense_key="sentinel_turret",
            amount=qty,
            conn=conn,
        )
        assert ok, reason
        unit = unit_build_seconds("sentinel_turret", 1, conn=conn, planet_id=pid)
        cap = orbital_production_batch_capacity(1)
        batch_remaining = production_job_duration_seconds(
            unit_seconds=unit, amount=qty, batch_capacity=cap
        )
        serial_remaining = qty * unit
        assert batch_remaining < serial_remaining

        begin_write_transaction(conn)
        credit(uid, serial_remaining + 10_000, "test", conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, reason, result = apply_timekeeper(
            uid, "defense", planet_id=pid, mode="finish", conn=conn
        )
        assert ok, reason
        commit(conn)

        applied = int(result.get("seconds_applied") or 0)
        assert applied <= batch_remaining + 2
        assert applied < serial_remaining
    finally:
        conn.close()


def test_timekeeper_shipyard_boost_shifts_started_at_and_survives_client(timekeeper_db):
    """GC-PERF-TK-001: finish-only boosts were wiped by started_at-based remaining."""
    from game.shipyard import build_ship
    from game.shipyard_queue import shipyard_queue_for_client, sync_shipyard_queue_finish_times

    conn = db()
    try:
        uid = _player(conn=conn)
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        cur = conn.cursor()
        cur.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (5_000_000, 5_000_000, 500_000, pid),
        )
        _grant_shipyard_tk_prereqs(cur, pid, uid)
        conn.commit()

        ok, reason, _ = build_ship(
            player_id=uid, planet_id=pid, ship_key="mule_courier", amount=20, conn=conn
        )
        assert ok, reason

        row = conn.execute(
            "SELECT id, started_at, finish_at FROM shipyard_queue WHERE planet_id = ? ORDER BY id LIMIT 1;",
            (pid,),
        ).fetchone()
        assert row is not None
        start_before = float(row["started_at"] or 0)
        finish_before = float(row["finish_at"] or 0)
        assert start_before > 0
        rem_before = finish_before - time.time()
        assert rem_before > 60

        boost = 120
        begin_write_transaction(conn)
        credit(uid, boost + 60, "test", conn=conn)
        ok, reason, result = apply_timekeeper(
            uid, "shipyard", planet_id=pid, mode="max", conn=conn
        )
        assert ok, reason
        applied = int(result.get("seconds_applied") or 0)
        assert applied >= 60
        commit(conn)

        row2 = conn.execute(
            "SELECT started_at, finish_at FROM shipyard_queue WHERE id = ?;",
            (int(row["id"]),),
        ).fetchone()
        if row2 is None:
            # Boost finished the whole batch — also success.
            return
        # Head start must move earlier so started_at-based remaining stays boosted
        # (unless a unit boundary reset started_at to now after delivering).
        start_after = float(row2["started_at"] or 0)
        finish_after = float(row2["finish_at"] or 0)
        assert finish_after < finish_before - 50 or start_after < start_before - 50

        sync_shipyard_queue_finish_times(pid, 1, conn=conn, now=time.time())
        client = shipyard_queue_for_client(uid, pid, 1, conn=conn, now=time.time())
        jobs = client.get("jobs") or client.get("queue") or []
        assert jobs
        rem_after = int(jobs[0].get("remaining") or jobs[0].get("remaining_seconds") or 0)
        assert rem_after < rem_before - 40
    finally:
        conn.close()
