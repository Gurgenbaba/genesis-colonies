"""GC-900B-1 — Buildings EN locale backfill guards."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
BUILDING_ORDER = [
    "metal_mine", "crystal_mine", "solar_plant", "fuel_cell_plant", "research_lab", "academy",
    "metal_storage", "crystal_storage", "fuel_storage", "command_center", "orbital_shipyard",
    "defense_factory", "barracks", "radar_array", "shield_generator", "terraformer", "nanofactory",
    "geothermal_nexus", "planet_core_nexus",
]
BUILDINGS_SCOPE_PREFIXES = (
    "buildings_", "building_", "desc_", "build_queue", "msg_build_", "hud_storage",
    "label_buildings", "label_level",
)


def _in_buildings_scope(key: str) -> bool:
    if any(key.startswith(p) for p in BUILDINGS_SCOPE_PREFIXES):
        return True
    return key in {f"building_{b}" for b in BUILDING_ORDER} or key in {f"desc_{b}" for b in BUILDING_ORDER}


@pytest.fixture
def en_data():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


@pytest.fixture
def de_data():
    return json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))


def test_gc900b1_building_label_keys_present_in_en(en_data, de_data):
    missing = []
    for b in BUILDING_ORDER:
        key = f"building_{b}"
        if key in de_data and key not in en_data:
            missing.append(key)
    assert not missing, f"missing building_* in en.json: {missing}"


def test_gc900b1_building_desc_keys_present_in_en(en_data, de_data):
    missing = []
    for b in BUILDING_ORDER:
        key = f"desc_{b}"
        if key in de_data and key not in en_data:
            missing.append(key)
    assert not missing, f"missing desc_* in en.json: {missing}"


def test_gc900b1_queue_and_hud_keys_present(en_data):
    required = (
        "build_queue_title",
        "build_queue_hint",
        "build_queue_remaining",
        "build_queue_time",
        "build_queue_target",
        "build_queue_level_short",
        "hud_storage_almost_full",
        "hud_storage_full",
        "label_buildings",
        "label_level",
        "msg_build_not_enough_resources_short",
    )
    missing = [k for k in required if k not in en_data]
    assert not missing, missing


def test_gc900b1_no_german_in_buildings_en(en_data):
    bad = {}
    for key, val in en_data.items():
        if not _in_buildings_scope(key) or not isinstance(val, str):
            continue
        if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
            bad[key] = val
    assert not bad, list(bad.items())[:5]


def test_gc900b1_building_labels_canonical_en(en_data):
    assert en_data["building_metal_mine"] == "Ferronite Mine"
    assert en_data["building_command_center"] == "Command Center"
    assert en_data["building_orbital_shipyard"] == "Orbital Shipyard"
    assert en_data["building_shield_generator"] == "Planetary Shield Generator"
    assert en_data["building_nanofactory"] == "Nanofactory"
    assert not re.search(r"Ferronit(?!e)", en_data["building_metal_mine"])


def test_gc900b1_i18n_build_queue_title_en():
    from game.i18n import get_locale_dict

    en = get_locale_dict("en")
    assert en.get("build_queue_title") == "Build queue"
    assert "Bauschleife" not in en.get("build_queue_title", "")


def test_gc900b1_buildings_scope_no_forbidden_terms(en_data):
    forbidden = ("Deuterium", "Metal Mine", "Crystal Mine", "Abbau-Pfad")
    hits = []
    for key, val in en_data.items():
        if not _in_buildings_scope(key):
            continue
        for term in forbidden:
            if term in val:
                hits.append(f"{key}: {term}")
    assert not hits, hits
