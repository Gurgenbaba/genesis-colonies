"""Trader Hub fuel cell exchange tests (unified exchange API)."""

from __future__ import annotations

import uuid

import pytest

from game import db as gdb
from game.db import db
from game.exchange import execute_exchange, get_exchange_config, get_exchange_status
from game.models import create_user, ensure_player_and_homeworld, init_db


@pytest.fixture
def fuel_ex_db(tmp_path, monkeypatch):
    db_path = tmp_path / "fuel_ex.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_buy_fuel_cells_costs_metal_and_crystal(fuel_ex_db):
    ok, _, user = create_user(f"fuel_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        cur = conn.cursor()
        cur.execute("SELECT id, metal, crystal, fuel_cells FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        row = dict(cur.fetchone())
        planet_id = int(row["id"])
        cur.execute(
            "UPDATE planets SET metal = 50000, crystal = 50000 WHERE id = ?;",
            (planet_id,),
        )
        conn.commit()

        cfg = get_exchange_config(conn=conn)
        metal_per = max(1, int(cfg["fuel_metal_per_unit"]))
        crystal_per = max(1, int(cfg["fuel_crystal_per_unit"]))
        units = 100
        assert metal_per > 0 and crystal_per > 0

        ok_b, reason, result = execute_exchange(
            player_id=uid,
            planet_id=planet_id,
            from_resource="metal",
            to_resource="fuel_cells",
            amount=units * metal_per,
            conn=conn,
        )
        assert ok_b, reason
        assert result is not None
        assert result.get("receive_resource") == "fuel_cells"
        assert int(result.get("receive_amount") or 0) >= units

        cur.execute("SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;", (planet_id,))
        after = dict(cur.fetchone())
        assert float(after["fuel_cells"]) >= float(row["fuel_cells"]) + units
        assert float(after["metal"]) < 50000.0
    finally:
        conn.close()


def test_fuel_exchange_status_ready(fuel_ex_db):
    ok, _, user = create_user(f"fx_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    conn = db()
    try:
        ensure_player_and_homeworld(uid, conn=conn)
        cur = conn.cursor()
        cur.execute("SELECT id, metal, crystal, fuel_cells FROM planets WHERE player_id = ? LIMIT 1;", (uid,))
        row = dict(cur.fetchone())
        planet_id = int(row["id"])
        st = get_exchange_status(
            player_id=uid,
            planet_id=planet_id,
            metal=float(row["metal"] or 0),
            crystal=float(row["crystal"] or 0),
            fuel_cells=float(row["fuel_cells"] or 0),
            conn=conn,
        )
        assert st.get("enabled") is True
        assert st.get("fuel_enabled") is True
        routes = st.get("routes") or {}
        assert routes.get("metal_to_fuel_cells", {}).get("enabled") is True
    finally:
        conn.close()
