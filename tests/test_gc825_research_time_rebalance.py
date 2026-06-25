"""GC-825 — research time & cost rebalance (anchor pacing after GC-821)."""

from __future__ import annotations

import math

import pytest

from game.economy_balance import (
    RESEARCH_COST_ANCHOR_TOTAL,
    RESEARCH_TIME_ANCHOR_HOURS,
    legacy_research_base_time_seconds,
    legacy_research_upgrade_cost,
    research_base_time_seconds,
    research_time_anchor_hours,
    research_upgrade_cost,
)
from game.effects import EffectResolver
from game.research import RESEARCH_TECHS, get_research_cost, get_research_time


_NEUTRAL_SETTINGS = {"build_speed": 1.0, "research_speed": 1.0}


def _neutral_resolver(*, research=None, lab=1):
    return EffectResolver(
        {"research_lab": int(lab)},
        dict(research or {}),
        settings=_NEUTRAL_SETTINGS,
    )


def test_legacy_l34_was_years_not_hours():
    """Pre-GC-825 exponential curve was unplayable at midgame."""
    legacy_s = legacy_research_base_time_seconds(840.0, 1.6, 34)
    assert legacy_s > 3600 * 24 * 365  # > 1 year


def test_gc825_l34_energy_under_five_days_neutral():
    er = _neutral_resolver()
    seconds = er.get_research_time_seconds("energy_tech", 34)
    hours = seconds / 3600.0
    assert hours < 120.0, f"expected <5d, got {hours:.1f}h"
    assert hours > 12.0


def test_gc825_l33_to_l34_not_years():
    er = _neutral_resolver()
    t33 = er.get_research_time_seconds("energy_tech", 33)
    t34 = er.get_research_time_seconds("energy_tech", 34)
    assert t34 < 3600 * 24 * 14
    assert t34 > t33


@pytest.mark.parametrize(
    "level,max_hours",
    [
        (10, 6.0),
        (20, 12.0),
        (30, 60.0),
        (40, 120.0),
        (60, 24 * 21),
        (80, 24 * 60),
    ],
)
def test_gc825_anchor_hours_caps(level: int, max_hours: float):
    er = _neutral_resolver()
    seconds = er.get_research_time_seconds("energy_tech", level)
    hours = seconds / 3600.0
    anchor = research_time_anchor_hours(level)
    assert hours == pytest.approx(anchor, rel=0.02)
    assert hours <= max_hours


def test_research_time_grows_monotonically():
    er = _neutral_resolver()
    prev = 0
    for lvl in range(1, 101, 5):
        cur = er.get_research_time_seconds("energy_tech", lvl)
        assert cur >= prev
        prev = cur


def test_buildtime_tech_reduces_research_duration():
    er_slow = _neutral_resolver(research={"buildtime_tech": 0})
    er_fast = _neutral_resolver(research={"buildtime_tech": 5})
    slow = er_slow.get_research_time_seconds("energy_tech", 20)
    fast = er_fast.get_research_time_seconds("energy_tech", 20)
    assert fast < slow


def test_research_lab_speeds_up_research():
    er_lab1 = _neutral_resolver(lab=1)
    er_lab5 = _neutral_resolver(lab=5)
    t1 = er_lab1.get_research_time_seconds("mining_tech", 15)
    t5 = er_lab5.get_research_time_seconds("mining_tech", 15)
    assert t5 < t1


def test_research_cost_l34_hardened_vs_legacy():
    m, c = get_research_cost("energy_tech", 34)
    leg_m, leg_c = legacy_research_upgrade_cost(1000, 500, 1.6, 34)
    assert m + c >= 750_000
    assert m + c < leg_m + leg_c
    assert leg_m + leg_c > 10_000_000


def test_higher_tier_tech_costs_more_at_same_level():
    m_energy, c_energy = get_research_cost("energy_tech", 25)
    m_nav, c_nav = get_research_cost("navigation_tech", 25)
    assert m_nav + c_nav > m_energy + c_energy


def test_get_research_time_wires_through_resolver(tmp_path, monkeypatch):
    """Integration: get_research_time uses GC-825 base curve + DB context."""
    import game.db as dbmod
    import game.models as models
    import uuid
    from game.models import create_user, ensure_player_and_homeworld, init_db, save_planet_buildings

    db_file = tmp_path / "gc825_research.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("BUILD_SPEED", "1")
    monkeypatch.setenv("RESEARCH_SPEED", "1")
    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    init_db()
    import migrate

    migrate.main()

    uname = f"gc825_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    from game.models import get_homeworld

    planet = get_homeworld(player_id=uid)
    save_planet_buildings(int(planet["id"]), {"research_lab": 3, "solar_plant": 5})

    seconds = get_research_time("energy_tech", 34, uid)
    hours = seconds / 3600.0
    assert hours < 120.0


def test_anchor_map_covers_benchmark_levels():
    for lvl in (10, 20, 30, 40, 60, 80, 100, 120):
        assert lvl in RESEARCH_TIME_ANCHOR_HOURS
        assert research_base_time_seconds(lvl) == pytest.approx(
            RESEARCH_TIME_ANCHOR_HOURS[lvl] * 3600, rel=0.001
        )
    assert 50 in RESEARCH_COST_ANCHOR_TOTAL


def test_all_research_techs_have_positive_cost_and_time():
    er = _neutral_resolver()
    for key, cfg in RESEARCH_TECHS.items():
        m, c = research_upgrade_cost(
            int(cfg["base_cost_m"]),
            int(cfg["base_cost_c"]),
            5,
        )
        assert m > 0 and c >= 0
        t = er.get_research_time_seconds(key, 5)
        assert t >= 60
