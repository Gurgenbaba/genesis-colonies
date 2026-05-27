"""Tests for commander name display helpers."""

from game.player_display import (
    commander_display_name,
    commander_lookup_name,
    commander_name_candidates,
    strip_commander_prefix,
)


def test_strip_commander_prefix():
    assert strip_commander_prefix("Commander Bobby") == "Bobby"
    assert strip_commander_prefix("commander bobby") == "bobby"
    assert strip_commander_prefix("Bobby") == "Bobby"
    assert strip_commander_prefix("") == ""


def test_commander_display_and_lookup():
    assert commander_display_name("Commander Alpha") == "Alpha"
    assert commander_lookup_name("Commander Alpha") == "Commander Alpha"
    assert commander_lookup_name("Alpha") == "Alpha"


def test_commander_name_candidates():
    cands = commander_name_candidates("Bobby")
    assert "Bobby" in cands
    assert "Commander Bobby" in cands
