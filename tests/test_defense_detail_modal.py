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
    assert card["icon"].endswith("plasma_arc.png")
    prod = card.get("production") or {}
    assert prod.get("cycle_seconds", 0) > 0
    assert prod.get("effective_batch_capacity", 0) >= 1


def test_build_defense_detail_card_with_requirements():
    card, err = build_defense_detail_card(
        "ion_bastion",
        buildings={"defense_factory": 4, "orbital_shipyard": 3},
        research={"weapon_tech": 6, "armor_tech": 3},
    )
    assert err is None
    assert card is not None
    assert card.get("requirements_items")
    prod = card.get("production") or {}
    assert prod.get("yard_batch_capacity", 0) > prod.get("effective_batch_capacity", 0)


def test_build_defense_detail_card_unknown():
    card, err = build_defense_detail_card("unknown_turret_xyz")
    assert card is None
    assert err == "defense_detail_not_found"


def test_defense_locked_template_uses_requirements_items_hover():
    from pathlib import Path

    tpl = (Path(__file__).resolve().parents[1] / "templates/partials/progression_cards.html").read_text(
        encoding="utf-8"
    )
    chunk = tpl.split("macro render_defense_locked_req_hover_attrs")[1].split("endmacro")[0]
    assert "unit.requirements_items" in chunk
