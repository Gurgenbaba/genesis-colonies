"""Defense detail modal — API and card payload."""

from __future__ import annotations

from game.defense_detail import build_defense_detail_card


def test_build_defense_detail_card_known_unit():
    card, err = build_defense_detail_card("plasma_arc")
    assert err is None
    assert card is not None
    assert card["defense_key"] == "plasma_arc"
    assert card["attack"] >= 0
    assert card["score_value"] > 0
    assert card["icon"].endswith("plasma_arc.svg")


def test_build_defense_detail_card_with_requirements():
    card, err = build_defense_detail_card(
        "ion_bastion",
        buildings={"defense_factory": 4},
        research={"weapon_tech": 6, "armor_tech": 3},
    )
    assert err is None
    assert card is not None
    assert card.get("requirements_items")


def test_build_defense_detail_card_unknown():
    card, err = build_defense_detail_card("unknown_turret_xyz")
    assert card is None
    assert err == "defense_detail_not_found"
