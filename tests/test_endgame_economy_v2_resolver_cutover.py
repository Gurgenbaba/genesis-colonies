from decimal import Decimal

import pytest

from game import production_formula as pf
from game.effects import EffectResolver


def _resolver(research, *, mine_level=120):
    level = int(mine_level)
    return EffectResolver(
        {
            "metal_mine": level,
            "crystal_mine": level,
            "fuel_cell_plant": level,
            "solar_plant": level,
        },
        dict(research),
        settings={"production_speed": 1.0, "build_speed": 1.0, "research_speed": 1.0},
    )


def test_active_research_tail_is_authoritative_inside_resolver(monkeypatch):
    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    research = {"mining_tech": 240, "crystal_tech": 240, "drone_tech": 240}
    resolver = _resolver(research)
    mods = resolver.get_modifiers()

    expected_metal = pf.research_modifier_for("metal", research)
    expected_crystal = pf.research_modifier_for("crystal", research)

    assert mods["metal_prod_factor"] == pytest.approx(expected_metal, rel=1e-12)
    assert mods["crystal_prod_factor"] == pytest.approx(expected_crystal, rel=1e-12)
    assert resolver.prod_overlay_factor("metal") == pytest.approx(1.0, rel=1e-12)
    assert resolver.prod_overlay_factor("crystal") == pytest.approx(1.0, rel=1e-12)


def test_active_output_uses_diminished_research_at_same_pivot_mine(monkeypatch):
    research = {"mining_tech": 240, "crystal_tech": 240, "drone_tech": 240}

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    legacy = _resolver(research, mine_level=120).production_per_hour_exact(1.0)[0]

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    active = _resolver(research, mine_level=120).production_per_hour_exact(1.0)[0]

    assert isinstance(active, Decimal)
    assert active > 0
    assert active < legacy


def test_levels_through_120_remain_resolver_equivalent(monkeypatch):
    research = {"mining_tech": 120, "crystal_tech": 120, "drone_tech": 120}

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    legacy = _resolver(research, mine_level=120).production_per_hour_exact(1.0)

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "active")
    active = _resolver(research, mine_level=120).production_per_hour_exact(1.0)

    assert active == legacy


def test_shadow_keeps_live_resolver_research_legacy(monkeypatch):
    research = {"mining_tech": 240, "crystal_tech": 240, "drone_tech": 240}

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "legacy")
    legacy = _resolver(research, mine_level=120).production_per_hour_exact(1.0)

    monkeypatch.setattr(pf, "ENDGAME_ECONOMY_MODE", "shadow")
    shadow = _resolver(research, mine_level=120).production_per_hour_exact(1.0)

    assert shadow == legacy
