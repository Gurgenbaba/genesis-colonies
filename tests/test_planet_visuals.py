"""Planet landscape mapping by galaxy slot."""

from __future__ import annotations

import pytest

from game.planet_visuals import (
    DEFAULT_LANDSCAPE,
    get_landscape_for_position,
    landscape_filename_for_planet,
    landscape_static_relpath,
)


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (1, "trockenplanet01-h.jpg"),
        (2, "trockenplanet04-h.jpg"),
        (3, "trockenplanet06-h.jpg"),
        (4, "trockenplanet08-h.jpg"),
        (5, "normaltempplanet04-h.jpg"),
        (6, "normaltempplanet03-h.jpg"),
        (7, "normaltempplanet01-h.jpg"),
        (8, "wasserplanet07-h.jpg"),
        (9, "wasserplanet08-h.jpg"),
        (10, "dschungelplanet08-h.jpg"),
        (11, "dschungelplanet07-h.jpg"),
        (12, "gasplanet05-h.jpg"),
        (13, "eisplanet04-h.jpg"),
        (14, "eisplanet06-h.jpg"),
        (15, "eisplanet09-h.jpg"),
    ],
)
def test_get_landscape_for_position_mapping(position: int, expected: str) -> None:
    assert get_landscape_for_position(position) == expected


@pytest.mark.parametrize("invalid", [0, -1, 16, 99, "x", None])
def test_get_landscape_for_position_fallback(invalid) -> None:
    assert get_landscape_for_position(invalid) == DEFAULT_LANDSCAPE


def test_landscape_static_relpath() -> None:
    assert landscape_static_relpath(8) == "img/landscapes/wasserplanet07-h.jpg"


def test_landscape_filename_for_planet() -> None:
    assert landscape_filename_for_planet({"position": 13}) == "eisplanet04-h.jpg"
    assert landscape_filename_for_planet({}) == DEFAULT_LANDSCAPE
    assert landscape_filename_for_planet(None) == DEFAULT_LANDSCAPE


def test_planet_identity_ice_world_accent() -> None:
    from game.planet_visuals import get_planet_identity_for_position, herocard_static_relpath

    ident = get_planet_identity_for_position(15)
    assert ident["landscape"] == "eisplanet09-h.jpg"
    assert ident["herocard"] == "herocard_15.png"
    assert herocard_static_relpath(15) == "img/herocards/herocard_15.png"
    assert ident["accent_color"] == "#3ff8ff"
    assert ident["secondary_color"] == "#6ccfff"
    assert ident["effect"] == "ice"
    assert ident["label_key"] == "planet_slot_15"


def test_planet_theme_matches_landscape_position() -> None:
    from game.planet_visuals import get_planet_identity_for_position, get_landscape_for_position

    for pos in range(1, 16):
        ident = get_planet_identity_for_position(pos)
        assert ident["landscape"] == get_landscape_for_position(pos)
        assert ident["herocard"] == f"herocard_{pos:02d}.png"
        assert ident["label_key"] == f"planet_slot_{pos:02d}"
        assert ident["accent_color"].startswith("#")
        assert ident["effect"]


def test_temperature_range_monotonic_by_position() -> None:
    from game.planet_visuals import temperature_range_for_position

    prev_max = None
    for pos in range(1, 16):
        temp = temperature_range_for_position(pos)
        assert temp["min_c"] < temp["max_c"]
        assert "°C" in temp["display"]
        if prev_max is not None:
            assert temp["max_c"] < prev_max
            assert temp["min_c"] < prev_max
        prev_max = temp["max_c"]

    hottest = temperature_range_for_position(1)
    coldest = temperature_range_for_position(15)
    assert hottest["min_c"] > 300
    assert coldest["max_c"] < -100


def test_planet_theme_keys_by_position() -> None:
    from game.planet_visuals import planet_theme_for_planet

    expected = {
        1: ("inferno", "hot"),
        2: ("magma", "hot"),
        3: ("ash", "hot"),
        4: ("barren-fireland", "arid"),
        5: ("crimson-desert", "arid"),
        6: ("golden-desert", "arid"),
        7: ("arid-frontier", "arid"),
        8: ("temperate-highlands", "living"),
        9: ("forest-world", "living"),
        10: ("jungle-prime", "living"),
        11: ("ocean-world", "living"),
        12: ("tundra-world", "frozen"),
        13: ("glacier-world", "frozen"),
        14: ("deep-frost", "frozen"),
        15: ("absolute-zero", "frozen"),
    }
    for pos, (theme_key, theme_group) in expected.items():
        theme = planet_theme_for_planet({"position": pos})
        assert theme["theme_key"] == theme_key
        assert theme["theme_group"] == theme_group
        assert theme["glow_color"] == theme["accent_color"]
        assert theme["landscape_relpath"].startswith("img/landscapes/")


def test_temperature_range_invalid_position_uses_temperate_default() -> None:
    from game.planet_visuals import temperature_range_for_position

    temp = temperature_range_for_position(99)
    assert temp["display"] == "5°C … 35°C"
    assert temp["position"] == 0


def test_planet_theme_default_keys() -> None:
    from game.planet_visuals import DEFAULT_THEME_GROUP, DEFAULT_THEME_KEY, planet_theme_for_planet

    theme = planet_theme_for_planet({})
    assert theme["theme_key"] == DEFAULT_THEME_KEY
    assert theme["theme_group"] == DEFAULT_THEME_GROUP
