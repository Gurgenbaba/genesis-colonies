from pathlib import Path

import game.buildings as buildings_mod
from game.mine_evolution.nodebuster import QUEUE_SAFETY_SENTINEL


ROOT = Path(__file__).resolve().parents[1]


def test_nodebuster_enqueue_cap_is_only_internal_safety_sentinel():
    assert buildings_mod._effective_building_queue_cap(
        "metal_mine",
        200,
        planet_id=1,
        evolution_rank=0,
    ) == QUEUE_SAFETY_SENTINEL
    assert buildings_mod._effective_building_queue_cap(
        "metal_mine",
        200,
        planet_id=1,
        evolution_rank=999,
    ) == QUEUE_SAFETY_SENTINEL
    # GC-ENDGAME-ENERGY-001: Solar shares the no-max queue contract under
    # Nodebuster, but remains outside Mine Ascension/AP.
    assert buildings_mod._effective_building_queue_cap(
        "solar_plant",
        200,
        planet_id=1,
    ) == QUEUE_SAFETY_SENTINEL


def test_mine_template_keeps_ascension_controls_without_skill_tree():
    template = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    assert "data-nodebuster-mine" in template
    assert "mine_ascension_title" in template
    assert "data-nodebuster-points-gain" in template
    assert "data-mine-evolve" in template
    assert "nodebuster_unlock_hint" not in template
    assert "data-nodebuster-skill" not in template


def test_queue_owner_contains_nodebuster_rebuild_scaling():
    source = (ROOT / "game" / "buildings.py").read_text(encoding="utf-8")
    assert "def _nodebuster_rebuild_bps(" in source
    assert "rebuild_cost_bps" in source
    assert "rebuild_time_bps" in source
    assert "_scale_bps(" in source


def test_solar_is_unbounded_in_queue_but_not_an_ascension_mine():
    from game.mine_evolution import is_evolvable_mine

    assert is_evolvable_mine("solar_plant") is False
