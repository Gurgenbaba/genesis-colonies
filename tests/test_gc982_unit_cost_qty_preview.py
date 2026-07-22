"""
GC-982 — Shipyard/Defense unit cards show total cost for entered quantity.

Run: python -m pytest tests/test_gc982_unit_cost_qty_preview.py -v
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_main_js_unit_cost_qty_preview_helpers():
    src = _read("static/main.js")
    assert "function renderUnitCostStackHtml(unitCosts, resources, amount)" in src
    assert "function syncUnitCardCostPreview(card, resources)" in src
    assert "function resolveUnitCardPreviewQty(qtyInp)" in src
    assert "function storeUnitCardUnitCosts(costWrap, unitCosts)" in src
    assert "initMilitaryUnitCostPreviewDelegation()" in src
    # GC-PERF-JS-002 — shipyard binder in pages/shipyard.js
    bind_sy = _read("static/js/pages/shipyard.js").split("function bindShipyardOnce()")[1].split(
        "function initShipyard"
    )[0]
    assert "syncUnitCardCostPreview(cardMax, militaryPageResources(page))" in bind_sy
    bind_def = src.split("function bindDefenseOnce()")[1].split("function initDefense")[0]
    assert "syncUnitCardCostPreview(card, militaryPageResources(page))" in bind_def


def test_shipyard_template_stores_unit_cost_basis():
    tpl = _read("templates/shipyard.html")
    assert "data-unit-cost-metal=" in tpl
    assert "data-unit-cost-crystal=" in tpl


def test_defense_template_stores_unit_cost_basis():
    tpl = _read("templates/defense.html")
    assert "data-unit-cost-metal=" in tpl
    assert "data-unit-cost-crystal=" in tpl


@pytest.fixture
def shipyard_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc982_shipyard.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_shipyard_build_amount_10_charges_total_unit_cost(shipyard_db):
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player
    from game.shipyard import _unit_build_cost, build_ship

    conn = db()
    ok, _, user = create_user(f"gc982_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;", (pid,))
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
            VALUES (?, ?, 10)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (uid, tech),
        )
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (10_000_000, 10_000_000, 500_000, pid),
    )
    conn.commit()

    unit = _unit_build_cost("mule_courier")
    amount = 10
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    before = cur.fetchone()
    ok, reason, result = build_ship(
        player_id=uid, planet_id=pid, ship_key="mule_courier", amount=amount, conn=conn
    )
    assert ok, reason
    assert result["cost"]["metal"] == unit["metal"] * amount
    assert result["cost"]["crystal"] == unit["crystal"] * amount
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    after = cur.fetchone()
    assert float(before["metal"]) - float(after["metal"]) == unit["metal"] * amount
    assert float(before["crystal"]) - float(after["crystal"]) == unit["crystal"] * amount
    conn.close()


@pytest.fixture
def defense_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc982_defense.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def test_defense_build_amount_10_charges_total_unit_cost(defense_db):
    from game.db import db
    from game.defense import build_defense, unit_build_cost
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player

    conn = db()
    ok, _, user = create_user(f"gc982d_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute("UPDATE planet_buildings SET defense_factory = 1 WHERE planet_id = ?;", (pid,))
    cur.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, 'weapon_tech', 2)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (uid,),
    )
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (10_000_000, 10_000_000, pid),
    )
    conn.commit()

    unit = unit_build_cost("sentinel_turret")
    amount = 10
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    before = cur.fetchone()
    ok, reason, result = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=amount, conn=conn
    )
    assert ok, reason
    assert result["cost"]["metal"] == unit["metal"] * amount
    assert result["cost"]["crystal"] == unit["crystal"] * amount
    cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (pid,))
    after = cur.fetchone()
    assert float(before["metal"]) - float(after["metal"]) == unit["metal"] * amount
    assert float(before["crystal"]) - float(after["crystal"]) == unit["crystal"] * amount
    conn.close()
