"""Regression for Research Lab Ascension on first light-PJAX Buildings entry."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_research_ascension_binder_is_loaded_from_persistent_shell():
    rail = (ROOT / "templates" / "partials" / "header_icon_rail.html").read_text(encoding="utf-8")

    assert "js/pages/research_lab_ascension.js" in rail
    assert "<script defer" in rail
    assert "-global1" in rail


def test_ready_hint_is_hidden_when_real_ascension_cta_exists():
    rail = (ROOT / "templates" / "partials" / "header_icon_rail.html").read_text(encoding="utf-8")
    buildings = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")

    assert "[data-research-lab-ascension]:has(> [data-research-lab-ascend]) > .hint" in rail
    assert "display: none !important" in rail
    assert "data-research-lab-ascend" in buildings


def test_existing_binder_stays_persistent_and_removes_special_wrapper():
    src = (ROOT / "static" / "js" / "pages" / "research_lab_ascension.js").read_text(encoding="utf-8")

    assert "GC._researchLabAscensionPersistentBound" in src
    assert "new MutationObserver(queueNormalize)" in src
    assert 'document.addEventListener("click", onDocumentClick)' in src
    assert 'target.closest("[data-research-lab-ascend]")' in src
    assert "block.remove()" in src
    assert "GC.registerCleanup" not in src
