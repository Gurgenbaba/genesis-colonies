"""Ground troop detail card + surfaces smoke (capacity / techtree / scoring)."""

from __future__ import annotations

from game.scoring import compute_destroyed_raw_from_losses
from game.techtree import get_techtree_page_context
from game.troop_detail import build_troop_detail_card
from game.troop_defs import barracks_troop_capacity, troop_score_value


def test_build_troop_detail_card_known_unit():
    card, err = build_troop_detail_card("militia", buildings={"barracks": 2})
    assert err is None
    assert card is not None
    assert card["troop_key"] == "militia"
    assert card["attack"] > 0
    assert card["score_value"] == troop_score_value("militia")
    assert card["train_cost_metal"] > 0
    assert any(i["key"] == "barracks" and i["met"] for i in card["requirements_items"])


def test_build_troop_detail_card_unknown():
    card, err = build_troop_detail_card("unknown_troop_xyz")
    assert card is None
    assert err == "troop_detail_not_found"


def test_techtree_includes_troops_and_barracks_preview():
    ctx = get_techtree_page_context(
        buildings={"barracks": 5, "radar_array": 3, "shield_generator": 2},
        research={},
    )
    keys = [s["key"] for s in ctx["sections"]]
    assert "troops" in keys
    troop_section = next(s for s in ctx["sections"] if s["key"] == "troops")
    assert len(troop_section["nodes"]) >= 3
    buildings = next(s for s in ctx["sections"] if s["key"] == "buildings")
    by_key = {n["key"]: n for n in buildings["nodes"]}
    assert by_key["barracks"]["effect_preview"]["effect_value"] == barracks_troop_capacity(5)
    assert by_key["shield_generator"]["effect_preview"]["effect_value"] == 4
    assert by_key["radar_array"]["effect_preview"]["effect_value"] == 6


def test_destroyed_raw_includes_troop_losses():
    troop_pts = compute_destroyed_raw_from_losses({"militia": 10})
    assert troop_pts > 0
    assert compute_destroyed_raw_from_losses({"militia": 20}) > troop_pts
