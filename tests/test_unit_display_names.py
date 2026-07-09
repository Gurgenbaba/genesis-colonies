"""Canonical ship/defense display labels — must match in-game i18n (en)."""

from __future__ import annotations

import json
from pathlib import Path

from game.combat_models import unit_display_name
from game.defense_defs import DEFENSE_ORDER, defense_display_name
from game.fleet_defs import ACTIVE_SHIP_KEYS, ship_display_name

_LOCALES = Path(__file__).resolve().parents[1] / "locales"
_EN = json.loads((_LOCALES / "en.json").read_text(encoding="utf-8"))


def _en_label(name_key: str) -> str:
    return str(_EN.get(name_key) or "")


def test_all_active_ships_use_en_locale_display_names():
    for key in sorted(ACTIVE_SHIP_KEYS):
        spec_key = f"fleet_ship_{key}"
        expected = _en_label(spec_key)
        assert expected, f"missing en locale for {spec_key}"
        assert ship_display_name(key, locale="en") == expected


def test_all_defenses_use_en_locale_display_names():
    for key in DEFENSE_ORDER:
        spec_key = f"defense_{key}"
        expected = _en_label(spec_key)
        assert expected, f"missing en locale for {spec_key}"
        assert defense_display_name(key, locale="en") == expected


def test_unit_display_name_resolves_ship_and_defense():
    assert unit_display_name("falcon_interceptor", locale="en") == "Raptor Interceptor"
    assert unit_display_name("ironclad_frigate", locale="en") == "Aegis Frigate"
    assert unit_display_name("sentinel_turret", locale="en") == "Sentinel Turret"
    assert unit_display_name("flak_array", locale="en") == "Flak Array"


def test_canonical_names_not_internal_shorthand():
    """Regression: wrong dev nicknames must not appear as display labels."""
    assert ship_display_name("falcon_interceptor", locale="en") != "Raptor"
    assert ship_display_name("ironclad_frigate", locale="en") != "Ironclad"
    assert ship_display_name("spark_drone", locale="en") != "Vanguard"
    assert ship_display_name("mule_courier", locale="en") != "Mule"
