"""
GC-852 — Contract tests for documented Shipyard + Planet-Tech formulas (docs only; no runtime change).
"""

from __future__ import annotations

import math

import pytest

from game.planet_evolution.planet_research import (
    compute_planet_research_cost,
    compute_planet_research_time,
)
from game.shipyard import (
    BUILD_TIME_LEVEL_FACTOR,
    base_unit_seconds_for_ship,
    production_job_duration_seconds,
    unit_batch_capacity,
    unit_build_seconds,
)


@pytest.fixture
def evo_db(tmp_path, monkeypatch):
    db_path = tmp_path / "gc852_evo.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    from game.db import db
    from game.planet_evolution.bootstrap import backfill_all_planets_evolution
    from game.planet_evolution.definitions import reload_definitions

    conn = db()
    reload_definitions(conn)
    backfill_all_planets_evolution(conn)
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None


def _evo_planet_id(player_id: int) -> int:
    from game.db import db
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player

    uname = f"gc852_pe_{player_id}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    ensure_player_and_homeworld(uid, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.close()
    return pid


class TestGc852ShipyardFormula:
    """Matches FLEET_SYSTEM.md § Shipyard unit build time."""

    def test_unit_seconds_matches_documented_curve(self):
        base = base_unit_seconds_for_ship("mule_courier")
        assert base == 120
        for yard_lvl in (1, 2, 5, 10):
            expected = max(1, int(math.ceil(base * (BUILD_TIME_LEVEL_FACTOR ** (yard_lvl - 1)))))
            assert unit_build_seconds("mule_courier", yard_lvl) == expected

    def test_order_duration_matches_batch_formula(self):
        base = base_unit_seconds_for_ship("mule_courier")
        unit = unit_build_seconds("mule_courier", 1)
        cap = unit_batch_capacity(1, base)
        assert cap == 1
        assert production_job_duration_seconds(unit_seconds=unit, amount=10, batch_capacity=cap) == unit * 10


class TestGc852PlanetTechFormula:
    """Matches PLANET_EVOLUTION.md § Planet-Tech Kosten & Zeit."""

    def test_cost_exponential_per_target_level(self):
        factor = 1.5
        base_m, base_c = 800, 400
        for target in (1, 2, 3):
            m, c = compute_planet_research_cost("industry_t1_automation", target)
            mult = factor ** (target - 1)
            assert m == int(base_m * mult)
            assert c == int(base_c * mult)

    def test_time_depends_on_tier_not_target_level(self, evo_db):
        from game.db import db
        from game.planet_evolution.bootstrap import ensure_planet_evolution

        pid = _evo_planet_id(852)
        conn = db()
        ensure_planet_evolution(pid, conn)
        conn.commit()

        t1 = compute_planet_research_time(pid, "industry_t1_automation", 1, conn=conn)
        t3 = compute_planet_research_time(pid, "industry_t1_automation", 3, conn=conn)
        assert t1 == t3 == 480.0

        conn.close()

    def test_time_tier_multiplier_145(self, evo_db):
        from game.db import db
        from game.planet_evolution.bootstrap import ensure_planet_evolution
        from game.planet_evolution.definitions import get_research_def

        pid = _evo_planet_id(853)
        conn = db()
        ensure_planet_evolution(pid, conn)
        conn.commit()

        cfg = get_research_def("industry_t2_mining_path") or {}
        assert int(cfg.get("tier") or 0) == 2
        base_time = float(cfg.get("base_time") or 0)
        expected = max(1.0, base_time * (1.45 ** 1))
        actual = compute_planet_research_time(pid, "industry_t2_mining_path", 1, conn=conn)
        assert actual == expected

        conn.close()
