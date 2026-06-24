"""
GC-862 — Buildings resolver reuse & queue hotpath optimization.

Run: python -m pytest tests/test_gc862_buildings_hotpath_optimization.py -v
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from game.buildings import (
    BuildingsPanelContext,
    build_building_technical_data,
    get_build_queue_rows,
    get_planet_buildings,
    get_upgrade_cost,
    queue_build_for_planet,
    recalculate_build_queue_finish_times,
)
from game.models import add_build_job, db

pytest_plugins = ["tests.test_race_conditions"]


def test_gc862_technical_data_resolver_calls_bounded(isolated_db, monkeypatch):
    user_id, _planet = isolated_db
    conn = db()
    try:
        calls = {"n": 0}
        import game.buildings as bmod

        orig = bmod.get_effect_resolver

        def _counting_resolver(*args, **kwargs):
            calls["n"] += 1
            return orig(*args, **kwargs)

        monkeypatch.setattr(bmod, "get_effect_resolver", _counting_resolver)

        data, err = build_building_technical_data("metal_mine", user_id=user_id, conn=conn)
        assert err is None
        assert data and data["levels"]
        assert calls["n"] == 1
    finally:
        conn.close()


def test_gc862_recalculate_queue_times_unchained(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    now = time.time()

    add_build_job(planet_id, "metal_mine", now - 10, now + 40)
    add_build_job(planet_id, "metal_mine", now + 100, now + 200)
    add_build_job(planet_id, "crystal_mine", now + 300, now + 400)

    conn = db()
    try:
        recalculate_build_queue_finish_times(planet_id, user_id, conn=conn, now=now)
        conn.commit()
    finally:
        conn.close()

    rows = get_build_queue_rows(planet_id)
    assert len(rows) == 3
    assert float(rows[1]["start_time"]) == pytest.approx(float(rows[0]["finish_time"]), abs=2.0)
    assert float(rows[2]["start_time"]) == pytest.approx(float(rows[1]["finish_time"]), abs=2.0)


def test_gc862_recalculate_uses_single_resolver(isolated_db, monkeypatch):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    now = time.time()

    add_build_job(planet_id, "metal_mine", now + 10, now + 50)
    add_build_job(planet_id, "metal_mine", now + 60, now + 100)
    add_build_job(planet_id, "metal_mine", now + 110, now + 150)

    calls = {"n": 0}
    import game.buildings as bmod

    orig_for_queue = BuildingsPanelContext.for_queue_recalc

    def _wrapped_for_queue(*args, **kwargs):
        ctx = orig_for_queue(*args, **kwargs)
        orig_bts = ctx.build_time_seconds

        def _counting_bts(btype, lvl):
            calls["n"] += 1
            return orig_bts(btype, lvl)

        ctx.build_time_seconds = _counting_bts  # type: ignore[method-assign]
        return ctx

    monkeypatch.setattr(bmod.BuildingsPanelContext, "for_queue_recalc", _wrapped_for_queue)

    conn = db()
    try:
        recalculate_build_queue_finish_times(planet_id, user_id, conn=conn, now=now)
        conn.commit()
    finally:
        conn.close()

    assert calls["n"] == 3
    rows = get_build_queue_rows(planet_id)
    assert len(rows) == 3


def test_gc862_max_queue_identical_job_targets(isolated_db):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)
    lvl = int(buildings.get("metal_mine", 0) or 0)

    ok, reason, payload = queue_build_for_planet(
        planet, buildings, "metal_mine", user_id=user_id, queue_mode="max"
    )
    assert ok and reason == "ok"
    assert int(payload.get("jobs_queued") or 1) >= 2

    rows = get_build_queue_rows(planet_id)
    for i, row in enumerate(rows):
        expected_m, expected_c = get_upgrade_cost("metal_mine", lvl + i)
        assert int(row["cost_metal"]) == int(expected_m)
        assert int(row["cost_crystal"]) == int(expected_c)


def test_gc862_max_queue_reduces_db_reads(isolated_db, monkeypatch):
    user_id, planet = isolated_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)

    calls = {"buildings": 0, "queue": 0}
    import game.buildings as bmod

    orig_buildings = bmod.get_planet_buildings
    orig_queue = bmod.get_build_queue_rows

    def _count_buildings(pid, *, conn=None):
        calls["buildings"] += 1
        return orig_buildings(pid, conn=conn)

    def _count_queue(pid, *, conn=None):
        calls["queue"] += 1
        return orig_queue(pid, conn=conn)

    monkeypatch.setattr(bmod, "get_planet_buildings", _count_buildings)
    monkeypatch.setattr(bmod, "get_build_queue_rows", _count_queue)

    ok, reason, payload = queue_build_for_planet(
        planet, buildings, "metal_mine", user_id=user_id, queue_mode="max"
    )
    assert ok and reason == "ok"
    jobs = int(payload.get("jobs_queued") or 1)
    assert jobs >= 2
    assert calls["buildings"] == 1
    assert calls["queue"] == 2  # recalc + initial load; not per MAX iteration


def test_gc862_panel_context_caches_build_time_at_target():
    resolver = MagicMock()
    resolver.get_build_time_seconds.side_effect = lambda b, l: int(l) * 10
    resolver.get_max_building_level.return_value = 100
    resolver._settings = {}
    resolver.player_id = 1
    resolver.planet_id = 1
    resolver.planet_position = None
    resolver.galaxy_id = None
    resolver._conn = None

    ctx = BuildingsPanelContext(
        user_id=1,
        buildings={"metal_mine": 3},
        research_levels={},
        ratio=1.0,
        resolver=resolver,
        production_per_hour={},
    )

    import game.buildings as bmod

    orig_er = bmod.EffectResolver
    bmod.EffectResolver = MagicMock(side_effect=lambda *a, **k: resolver)

    try:
        assert ctx.build_time_seconds_at_target("metal_mine", 5) == 50
        assert ctx.build_time_seconds_at_target("metal_mine", 5) == 50
        assert bmod.EffectResolver.call_count == 1
    finally:
        bmod.EffectResolver = orig_er
