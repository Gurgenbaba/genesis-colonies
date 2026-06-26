"""GC-900B-3 — Fleet, shipyard and defense EN locale guards."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

FLEET_PREFIXES = ("fleet_", "shipyard_")
DEFENSE_PREFIXES = ("defense_",)
FLEET_STANDALONE = ("shipyard", "fleet_shipyard_title", "nav_shipyard")


def _in_fleet_scope(key: str) -> bool:
    if key.startswith(FLEET_PREFIXES) or key in FLEET_STANDALONE:
        return True
    return key.startswith("fleet_mission_") or key.startswith("fleet_ship_")


def _in_defense_scope(key: str) -> bool:
    return key.startswith(DEFENSE_PREFIXES)


@pytest.fixture
def en_data():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def test_gc900b3_shipyard_canonical_titles(en_data):
    assert en_data["shipyard"] == "Orbital Shipyard"
    assert en_data["fleet_shipyard_title"] == "Orbital Shipyard"
    assert en_data["nav_shipyard"] == "Orbital Shipyard"


def test_gc900b3_defense_planetary_title_en(en_data):
    assert en_data["defense_panel_planetary_title"] == "Planetary Defense"
    assert "Planetare" not in en_data["defense_panel_planetary_title"]


def test_gc900b3_fleet_defense_no_german(en_data):
    bad = []
    for key, val in en_data.items():
        if not (_in_fleet_scope(key) or _in_defense_scope(key)):
            continue
        if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
            bad.append(key)
    assert not bad, bad[:10]


def test_gc900b3_no_bare_shipyard_in_player_titles(en_data):
    hits = []
    for key in ("shipyard", "fleet_shipyard_title", "nav_shipyard"):
        val = en_data.get(key, "")
        if val == "Shipyard":
            hits.append(key)
    assert not hits, hits


def test_gc900b3_fleet_scope_no_forbidden_terms(en_data):
    forbidden = ("Deuterium", "Metal Mine", "Crystal Mine", "Abbau-Pfad", " HQ")
    hits = []
    for key, val in en_data.items():
        if not (_in_fleet_scope(key) or _in_defense_scope(key)):
            continue
        for term in forbidden:
            if term in val:
                hits.append(f"{key}: {term}")
    assert not hits, hits
