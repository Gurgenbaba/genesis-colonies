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
