"""Admin planet buildings bulk + player research + planet defense."""

from __future__ import annotations

import uuid

import pytest

from game import db as gdb
from game.admin_api import (
    get_planet_detail,
    set_planet_buildings_bulk,
    set_planet_defense_stock,
    set_player_research,
)
from game.db import db
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_planet_buildings,
    get_planet_defense,
    get_research_levels,
    init_db,
)


@pytest.fixture
def admin_editor_db(tmp_path, monkeypatch):
    db_path = tmp_path / "admin_editor.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player_planet():
    ok, err, user = create_user(f"ae_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Editor")
    conn = db()
    row = conn.execute(
        "SELECT id FROM planets WHERE player_id = ? ORDER BY id ASC LIMIT 1;",
        (uid,),
    ).fetchone()
    conn.close()
    assert row is not None
    return uid, int(row["id"])


def test_set_planet_buildings_bulk_and_caps(admin_editor_db):
    from unittest.mock import patch

    uid, planet_id = _player_planet()
    with patch("game.admin_api.audit"):
        res = set_planet_buildings_bulk(
            1,
            planet_id,
            {
                "buildings": {
                    "metal_storage": 15,
                    "crystal_storage": 12,
                    "fuel_storage": 10,
                    "metal_mine": 8,
                }
            },
        )
    assert res["ok"] is True
    b = get_planet_buildings(planet_id)
    assert b["metal_storage"] == 15
    assert b["crystal_storage"] == 12
    assert b["fuel_storage"] == 10
    assert b["metal_mine"] == 8
    detail = get_planet_detail(planet_id)
    assert detail["ok"] is True
    caps = detail.get("storage_caps") or {}
    assert int(caps.get("metal") or 0) > 0
    assert int(caps.get("crystal") or 0) > 0
    assert "building_keys" in detail
    assert "metal_storage" in detail["building_keys"]


def test_set_player_research(admin_editor_db):
    from unittest.mock import patch

    from game.research import RESEARCH_TECHS

    uid, _ = _player_planet()
    tech = next(iter(RESEARCH_TECHS.keys()))
    with patch("game.admin_api.audit"):
        res = set_player_research(1, uid, {"research": {tech: 7}})
    assert res["ok"] is True
    levels = get_research_levels(uid)
    assert int(levels.get(tech) or 0) == 7
    assert tech in (res.get("research_keys") or [])


def test_set_planet_defense_stock(admin_editor_db):
    from unittest.mock import patch

    from game.defense_defs import DEFENSE_ORDER

    uid, planet_id = _player_planet()
    key = DEFENSE_ORDER[0]
    with patch("game.admin_api.audit"):
        res = set_planet_defense_stock(1, planet_id, {"defense": {key: 25}, "mode": "set"})
    assert res["ok"] is True
    stock = get_planet_defense(planet_id)
    assert int(stock.get(key) or 0) == 25
