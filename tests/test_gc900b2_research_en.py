"""GC-900B-2 — Research EN locale backfill guards."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

RESEARCH_SCOPE_PREFIXES = (
    "research_",
    "techtree_",
    "research_effect",
    "desc_tech_",
)
RESEARCH_STANDALONE = (
    "btn_research",
    "open_research",
    "label_research",
    "header_technology",
    "mining_tech",
    "drone_tech",
    "storage_tech",
    "energy_tech",
)


def _research_tech_keys():
    from game.research import RESEARCH_TECHS

    keys: set[str] = set()
    for tech in RESEARCH_TECHS:
        keys.add(tech)
        keys.add(f"desc_{tech}")
        keys.add(f"tech_{tech}")
        keys.add(f"tech_{tech}_desc")
    return keys


def _in_research_scope(key: str, tech_keys: set[str]) -> bool:
    if any(key.startswith(p) for p in RESEARCH_SCOPE_PREFIXES):
        return True
    if key.startswith("tech_") and not key.startswith("techtree_"):
        return True
    if key in RESEARCH_STANDALONE or key in tech_keys:
        return True
    if key.startswith("overview_") and "research" in key:
        return True
    if key.startswith("msg_") and "research" in key:
        return True
    return False


@pytest.fixture
def en_data():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


@pytest.fixture
def de_data():
    return json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))


@pytest.fixture
def tech_keys():
    return _research_tech_keys()


def test_gc900b2_research_keys_present_in_en(en_data, de_data, tech_keys):
    missing = []
    for key in de_data:
        if not _in_research_scope(key, tech_keys):
            continue
        if key not in en_data:
            missing.append(key)
    assert not missing, f"missing research keys in en.json: {missing[:10]}"


def test_gc900b2_no_german_in_research_en(en_data, tech_keys):
    bad = {}
    for key, val in en_data.items():
        if not _in_research_scope(key, tech_keys) or not isinstance(val, str):
            continue
        if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
            bad[key] = val
        elif re.search(
            r"\b(Forschung|Stufe|Veredelung|Waffen|Panzerung|Schild|Kerntechnologien|Senkt|Optimiert)\b",
            val,
        ):
            bad[key] = val
    assert not bad, list(bad.items())[:5]


def test_gc900b2_research_labels_canonical_en(en_data):
    assert en_data["btn_research"] == "Start Research"
    assert en_data["label_research"] == "Research"
    assert en_data["tech_metal_refining"] == "Ferronite Refinement"
    assert not re.search(r"Ferronit(?!e)", en_data["tech_metal_refining"])


def test_gc900b2_research_scope_no_forbidden_terms(en_data, tech_keys):
    forbidden = ("Deuterium", "Metal Mine", "Crystal Mine", "Abbau-Pfad", "HQ")
    hits = []
    for key, val in en_data.items():
        if not _in_research_scope(key, tech_keys):
            continue
        for term in forbidden:
            if term in val:
                hits.append(f"{key}: {term}")
    assert not hits, hits


def test_gc900b2_i18n_research_title_en():
    from game.i18n import get_locale_dict

    en = get_locale_dict("en")
    assert en.get("research_title") == "Research"
    assert "Forschung" not in en.get("research_title", "")
