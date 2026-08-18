"""GC-900 — Locale terminology harmonization guards."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
TERMINOLOGY_DOC = ROOT / "docs" / "GENESIS_TERMINOLOGY.md"

_GERMAN_CHARS = re.compile(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]")

FORBIDDEN_IN_EN_VALUES = (
    "Ferronitee",
    "Abbau-Pfad",
    "Orbitalabbau",
    "Deuterium",
    "Mining Path",
    "Resource Path",
)

FORBIDDEN_IN_DE_VALUES = (
    "Deuterium",
    "Mining Path",
    "Resource Path",
    "Abbau-Pfad",
    "Metal Mine",
    "Crystal Mine",
    "Defense Factory",  # use Verteidigungsfabrik in DE UI
)

# Keys may contain legacy code names; values must not use OGame resource labels.
FORBIDDEN_OGAME_IN_VALUES = (
    re.compile(r"\bDeuterium\b", re.I),
    re.compile(r"\bMining Path\b", re.I),
    re.compile(r"\bResource Path\b", re.I),
)


@pytest.fixture(params=("de.json", "en.json"))
def locale_file(request):
    return request.param, json.loads((LOCALES / request.param).read_text(encoding="utf-8"))


def test_gc900_terminology_doc_exists():
    assert TERMINOLOGY_DOC.exists()
    text = TERMINOLOGY_DOC.read_text(encoding="utf-8")
    assert "Ferronit" in text
    assert "Ferronite" in text
    assert "Extraktionspfad" in text


def test_gc900_no_duplicate_keys_in_locale_files():
    for name in ("de.json", "en.json"):
        raw = (LOCALES / name).read_text(encoding="utf-8")
        keys = re.findall(r'"([^"\\]+)"\s*:', raw)
        seen: set[str] = set()
        dups: set[str] = set()
        for k in keys:
            if k in seen:
                dups.add(k)
            seen.add(k)
        assert not dups, f"duplicate keys in {name}: {sorted(dups)[:10]}"


def test_gc900_en_no_german_characters():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    bad = {k: v for k, v in en.items() if isinstance(v, str) and _GERMAN_CHARS.search(v)}
    assert not bad, f"German characters in en.json: {list(bad.items())[:5]}"


def test_gc900_en_uses_ferronite_not_ferronit():
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    bad = {
        k: v
        for k, v in en.items()
        if isinstance(v, str) and re.search(r"Ferronit(?!e)", v)
    }
    assert not bad, f"legacy Ferronit spelling in en.json: {list(bad.items())[:5]}"


def test_gc900_de_forbidden_terms():
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    hits: list[str] = []
    for key, val in de.items():
        if not isinstance(val, str):
            continue
        for term in FORBIDDEN_IN_DE_VALUES:
            if term in val:
                hits.append(f"{key}: {term}")
    assert not hits, "forbidden terms in de.json:\n" + "\n".join(hits[:20])


def test_gc900_no_ogame_terms_in_player_locales(locale_file):
    name, data = locale_file
    hits: list[str] = []
    for key, val in data.items():
        if not isinstance(val, str):
            continue
        for rx in FORBIDDEN_OGAME_IN_VALUES:
            if rx.search(val):
                hits.append(f"{name} {key}: {val[:60]}")
    assert not hits, "\n".join(hits[:15])


def test_gc900_research_mining_tech_canon():
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    from game.production_formula import MINING_TECH_PER_LEVEL

    pct = str(int(round(MINING_TECH_PER_LEVEL * 100)))
    assert de["mining_tech"] == "Ferronit-Veredelung"
    assert en["mining_tech"] == "Ferronite Refinement"
    assert f"{pct}%" in en["desc_mining_tech"] or f"{pct} %" in en["desc_mining_tech"]
    assert "Ferronite" in en["desc_mining_tech"]


def test_gc900_pe_extraction_path_canon():
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    assert "Extraktionspfad" in de["pe_industry_t2_mining_path"]
    assert "extraction" in en["pe_industry_t2_mining_path"].lower()


def test_gc900_locale_keys_still_valid():
    import subprocess
    import sys

    script = ROOT / "scripts" / "check_locale_keys.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
