"""GC-900B-4 — Planet Evolution and overview EN locale guards."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"

GERMAN_HINTS = (
    "Produktionskette",
    "Spezialisierung",
    "Forschung",
    "Kolonie",
    "Planetare",
    "Experimentelle",
    "Schmuggler",
    "Tiefbau",
    "Verteidigung",
    "Allianz",
    "Spieler",
    "bannen",
    "Einstellungen",
    "Verifizierungs",
)


def _in_pe_overview_scope(key: str) -> bool:
    return key.startswith(
        (
            "pe_",
            "desc_pe_",
            "spec_",
            "policy_",
            "overview_",
            "trait_",
            "chain_",
            "event_",
        )
    )


def _looks_german(val: str) -> bool:
    if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
        return True
    return any(h in val for h in GERMAN_HINTS)


@pytest.fixture
def en_data():
    return json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))


def test_gc900b4_pe_overview_keys_present(en_data):
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    missing = [k for k in de if _in_pe_overview_scope(k) and k not in en_data]
    assert not missing, missing[:10]


def test_gc900b4_no_german_in_pe_overview_en(en_data):
    bad = {k: v for k, v in en_data.items() if _in_pe_overview_scope(k) and _looks_german(v)}
    assert not bad, list(bad.items())[:5]


def test_gc900b4_overview_colony_en(en_data):
    assert en_data.get("overview_label_colony") == "Colony"


def test_gc900b4_pe_tab_research_en(en_data):
    assert en_data.get("pe_tab_research") == "Research"


def test_gc900b4_pe_spec_smuggler_en(en_data):
    assert "Schmuggler" not in en_data.get("spec_smuggler_colony", "")
